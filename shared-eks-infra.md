# Shared EKS infrastructure

The `../infra/terraform/xvp-exp-common` folder houses the infrastructure to deploy an EKS cluster for XVP

* in our AWS accounts
* with the TSF subnet rails
* the appropriate network & IAM settings
* providing control planes for functionality that is used by all XVP microservices

## Usage

The folder houses three relevant Terraform modules:

* `eks` - The EKS cluster and its resources
* `k8s` - Basic K8s configuration to provide common Kubernetes services
* `istio` - Core components for Istio Service Mesh

The pipeline files are located at `../ci/eks` which include a `config.yml` that belongs to `pipeline-eks.yml` to run the Terraform code in Concourse. See the [EKS Pipeline documentation](../ci/eks/README.md) for more details.

## Details

### Terraform

XVP uses the AWS and K8s provider in Terraform to build out all required resources.

When using interpolation to pass credentials to the Kubernetes provider from the AWS-EKS resources, these resources SHOULD NOT be created in the same Terraform module where Kubernetes provider resources are also used. This will lead to intermittent and unpredictable errors which are hard to debug and diagnose.

This is a [known issue in Terraform](https://github.com/hashicorp/terraform/issues/4149) and the only reliable workaround is to use a 'static values' as input parameters to generate the K8s credentials via `aws_eks_cluster_auth`. To achieve this, the `k8s` (root) module uses the `eks` (root) module output via the remote state itself. That way it is ensured that all values are known from `eks` in the `k8s` module during the `plan` phase.

More details can be found here:

* [https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs#stacking-with-managed-kubernetes-cluster-resources](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs#stacking-with-managed-kubernetes-cluster-resources)
* [https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/latest#usage-example](https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/latest#usage-example)

_Side note_: `data terraform_remote_state` does not natively support workspaces: The key to the `.tfstate` file must be constructed by hand.

#### `eks` module

Providing only the base EKS resources to bootstrap the cluster. Only the AWS provider is used. It consists of the following sub-modules

* `xvp-exp-common/eks/cluster`
  Providing only the base EKS resources to bootstrap the cluster. Only the AWS provider is used. It also provides all the IAM roles that are required for running a node group
* `xvp-exp-common/eks/cni`
  Running EKS specific `kubectl` commands to configure the cluster properly:
  * Create a proper `aws-auth` map so that IAM roles are respected in the EKS cluster. This must be executed before the first node group within the cluster is created! There exist a k8s provider based resource to properly create `aws-auth` - but this would break Terraform as it would create (again) a stacked resource situation
  * Install the CNI configuration for our subnet configuration (see below)
  * Performs the required changes to the `aws-node` daemonset.
    The daemonset is created by EKS itself so we can't create it via Terraform. Also, those changes must be in before the first node group is created
* `xvp-exp-common/eks/node-group`
  Creates an actual node group to run the shared concern services like DNS, ALB control plane etc. Node-affinity is configured between the node-group and the shared K8s services to ensure that each those services have a small node-group to run upon.
* `xvp-exp-common/eks/node-group-v2`
  node-group-v2 uses a launch template so the ec2 instances have proper names and not the AWS auto-generated. Also adds support for additional security groups.
* `xvp-exp-common/eks/perf-s3`
  Placeholder

#### `k8s` module

Provides all the additional shared concerns in the cluster - mainly provided by the K8s provider. The EKS cluster details are loaded via the `terraform_remote_state` and are therefore always known. It is safe to use the AWS provider here, too!

Shared concerns are at this point:

* DNS (provided by EKS)
* ALB control plane - to translate between `kubernetes_ingress` and the actual AWS ALB resources
* Autoscaler - Cluster autoscaler & HPA to resize nodes & pods including a metrics-server
* `config-api` service deployed in a resilient way so that all XVP microservices can access secrets

#### `istio` module

**NOTE:** The `istio` module is slated to be rolled into the `k8s` module to simplify the workflows ([XPINF-340](https://ccp.sys.comcast.net/browse/XPINF-340)).

The `istio` module installs the base components for the Istio Service Mesh, Ingress Gateways, Egress Gateways, and Rate Limiting features we currently utilize.

### Load Balancer

As of today we use a hybrid NLB and ALB as Load Balancers. While we are actively migrating services Istio Ingress Gateway via NLB **ONLY**, we will maintain the legacy ALB flow until all services are 100% migrated to the new flow.

#### NLB

The implementation of Istio Service Mesh in our cluster provides many benefits, one of which is centralizing inbound traffic flows through an Ingress Gateway Pod, or IGW. Before traffic flows to the IGW (and subsequent POD), it must first route through an AWS Network Load Balancer, or NLB. The NLB is a layer 4 load balancer that is used to terminate TLS traffic before forwarding to a target group consisting of IGW PODs. This allows us to maintain a single AWS Load Balancer resource to front all traffic in the cluster, as opposed to an individual ALB per service. The benefits to the flow are numerous:

* Fewer resources to manage
  * Single NLB vs 1 ALB per service
  * Wildcard certificate
* More efficient utilization of IP space
* More granular options for traffic flow control and rate limiting
* Better visibility and insight into traffic flows

The NLB is crated via the `AWS Load balancer control plane` that is installed via [Helm](../infra/terraform/xvp-exp-common/k8s/helm-alb.tf). As of writing this, the AWS LBC has been updated to a BETA version (`v2.4.4-nlb-sg.1`) which adds support for creating NLBs attached to Security Groups. This previously unsupported feature enables us to provision the NLB attached to the TSF Public Rail Security Group via the `"service.beta.kubernetes.io/aws-load-balancer-security-groups"` annotation.

#### ALB

* With EKS 1.19 the CLB behaves erratic:
  It does not attach to the tagged subnets (public rail) but randomly choose others (private + CNI during the last deploy). There is no way to tell the CLB (via `kubernetes_service`) which subnets to use as autodiscovery via tags is always used. But our tags on the subnets are as documented by AWS.
* xvp-session needs WAF. WAF only works with ALB (or another solution via Istio)
* Canary deployments (Argo) require ALB (or Istio) but don't work with CLB

The ALB is crated via the `AWS Load balancer control plane` that is installed via Helm. **Update here about BETA LBC for NLB Security Groups**
This pod reads the annotations from the `kubernetes_ingress` and performs the proper AWS API calls.

The AWS documentation asks to use OIDC for proper rights separation. But due to Comcast's Governance we can't use this. The workaround provided by `#aws` is to assign the rights to the node itself. Technically that means everything running on the node can perform those API calls and not only the
`AWS Load balancer control plane`.

### DNS

DNS records for the services (stable, canary, stable-nlb, canary-nlb) & the actual ALB resources are created in the [service-specific infrastructure](https://github.com/comcast-xvp/xvp/blob/main/docs/Platform/k8s/service-infra.md).

A cluster specific CNAME record is generated for the Kubernetes API endpoint to provide the Prometheus scraping with a fixed endpoint. Additionally, a cluster specific DNS record for [Kiali](#kiali-ui) is created for accessing the dashboards.

### Autoscaling

Autoscaling in K8s consists of two pieces:

1. Cluster Autoscaler (CA) is able to start and stop worker nodes (of the managed node group) to scale the computing/memory availability
1. Horizontal Pod Autoscaler (HPA) starts and stops pods to actually use the computing power

#### Cluster Autoscaler

CA scans the nodes based on the limit/resources of the pods deployed to them and _not_ based on the actual CPU usage at the point in time. This allows for some predictable behavior based on the amount of pods that are currently running (and are in `scheduled` state if there are not enough worker nodes available).

Without HPA in place, the scaling can be done manually and the concept becomes clear:

Given existing nodes, they can be inspected with `kubectl describe node ...` showing the currently requested resources by the pods as per the K8s deployments and not their actual use:

```text
Allocated resources:
  (Total limits may be over 100 percent, i.e., overcommitted.)
  Resource                    Requests    Limits
  --------                    --------    ------
  cpu                         710m (36%)  200m (10%)
  memory                      130Mi (4%)  250Mi (8%)
```

##### Scale out

Manually scaling out (ie.) via the replication set of the deployment `kubectl scale --replicas=6 xvp-disco-api...` shows the desire to scale out via  `kubectl describe deployment xvp-disco-api...`:

```text
Replicas: 6 desired | 6 updated | 6 total | 3 available | 3 unavailable
...
Events:
  Type    Reason             Age   From                   Message
  ----    ------             ----  ----                   -------
  Normal  ScalingReplicaSet  19m   deployment-controller  Scaled up replica set xvp-disco-api... to 3
  Normal  ScalingReplicaSet  5s    deployment-controller  Scaled up replica set xvp-disco-api... to 6
```

This causes a lot of pods to become available and enter `pending` state:

```bash
$ kubectl get pods -A
xvp-disco-api-dev   xvp-disco-api...   2/2     Running   0          21m
xvp-disco-api-dev   xvp-disco-api...   2/2     Running   0          21m
xvp-disco-api-dev   xvp-disco-api...   0/2     Pending   0          104s
xvp-disco-api-dev   xvp-disco-api...   2/2     Running   0          21m
xvp-disco-api-dev   xvp-disco-api...   0/2     Pending   0          104s
xvp-disco-api-dev   xvp-disco-api...   2/2     Running   0          104s
```

(3 additional pods as scale out from 3 -> 6)

This is detected by the AC:

```bash
$ kubectl logs -n kube-system cluster-autoscaler...
I0412 01:39:22.921113       1 filter_out_schedulable.go:79] Schedulable pods present
I0412 01:39:22.921194       1 klogx.go:86] Pod xvp-disco-api-dev-sj-cc/xvp-disco-api-dev-sj-cc-0-0-50-8fcb583a40759d8d41cab54e6f1jbcgs is unschedulable
I0412 01:39:22.921261       1 klogx.go:86] Pod xvp-disco-api-dev-sj-cc/xvp-disco-api-dev-sj-cc-0-0-50-8fcb583a40759d8d41cab54e6f1zkcpj is unschedulable
I0412 01:39:22.921326       1 klogx.go:86] Pod xvp-disco-api-dev-sj-cc/xvp-disco-api-dev-sj-cc-0-0-50-8fcb583a40759d8d41cab54e6f1shhm7 is unschedulable
I0412 01:39:22.921388       1 klogx.go:86] Pod xvp-disco-api-dev-sj-cc/xvp-disco-api-dev-sj-cc-0-0-50-8fcb583a40759d8d41cab54e6f1xm4pf is unschedulable
I0412 01:39:22.921461       1 klogx.go:86] Pod xvp-disco-api-dev-sj-cc/xvp-disco-api-dev-sj-cc-0-0-50-8fcb583a40759d8d41cab54e6f1jtf9h is unschedulable
I0412 01:39:22.921526       1 klogx.go:86] Pod xvp-disco-api-dev-sj-cc/xvp-disco-api-dev-sj-cc-0-0-50-8fcb583a40759d8d41cab54e6f1xc9jx is unschedulable
I0412 01:39:22.921601       1 klogx.go:86] Pod xvp-disco-api-dev-sj-cc/xvp-disco-api-dev-sj-cc-0-0-50-8fcb583a40759d8d41cab54e6f1wbt7z is unschedulable
I0412 01:39:22.921739       1 scale_up.go:364] Upcoming 9 nodes
I0412 01:39:22.928544       1 scale_up.go:400] Skipping node group eks-10bc6191-8af2-d74d-7de8-c5fed5ef5762 - max size reached
```

and the AC scales up - up to the maximum number defined in the node group/ASG (as reflected in the last line).

##### Scale in

On scale in, the reverse happens - ie. there are no pods scheduled on nodes. Right now AC is (default) configured to perform actions every 10 minutes (=cool down period).

AC detects underutilized nodes `kubectl logs -n kube-system cluster-autoscaler...`:

```text
1 scale_down.go:421] Node ip-96-103-156-157.ec2.internal - cpu utilization 0.367876
```

(This is the same percentage number as the node details at the top showed: `36%`)

This means nodes get scheduled for decommission:

```bash
$ kubectl get nodes
NAME                             STATUS                        ROLES    AGE    VERSION
ip-96-103-156-137.ec2.internal   Ready                         <none>   12m    v1.19.6-eks-49a6c0
ip-96-103-156-143.ec2.internal   Ready                         <none>   157m   v1.19.6-eks-49a6c0
ip-96-103-156-150.ec2.internal   Ready                         <none>   12m    v1.19.6-eks-49a6c0
ip-96-103-156-157.ec2.internal   Ready,SchedulingDisabled      <none>   104m   v1.19.6-eks-49a6c0
ip-96-103-156-185.ec2.internal   Ready                         <none>   12m    v1.19.6-eks-49a6c0
ip-96-103-156-234.ec2.internal   Ready,SchedulingDisabled      <none>   104m   v1.19.6-eks-49a6c0
ip-96-103-156-237.ec2.internal   Ready                         <none>   156m   v1.19.6-eks-49a6c0
ip-96-103-156-244.ec2.internal   NotReady,SchedulingDisabled   <none>   44m    v1.19.6-eks-49a6c0
```

and are removed after all (system) pods have been removed from the node.

#### Horizontal Pod Autoscaler

HPA is responsible to scale the pods itself and leverages CA to do so.

HPA requires a metrics-server that collects CPU and memory details. This metrics-server is _not_ meant for monitoring but for scaling only.

With the deployment of the metrics-server, `kubectl` provides a `top` command:

```bash
$ kubectl top node
NAME                             CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
ip-96-102-65-175.ec2.internal    63m          3%     903Mi           29%
ip-96-103-156-137.ec2.internal   60m          3%     1030Mi          34%
ip-96-103-156-238.ec2.internal   62m          3%     902Mi           29%
ip-96-103-156-245.ec2.internal   57m          2%     902Mi           29%
```

as also for pods:

```bash
$ kubectdl top pods -A
NAMESPACE                 NAME                                                              CPU(cores)   MEMORY(bytes)
amazon-cloudwatch         fluent-bit-fgc7r                                                  2m           35Mi
amazon-cloudwatch         fluent-bit-gn2rc                                                  2m           35Mi
amazon-cloudwatch         fluent-bit-hh4pr                                                  2m           35Mi
amazon-cloudwatch         fluent-bit-jlvv6                                                  2m           35Mi
kube-system               aws-load-balancer-controller-6b5958bbdc-ncp6q                     2m           36Mi
kube-system               aws-node-pjv6t                                                    5m           43Mi
kube-system               aws-node-rrfmk                                                    5m           43Mi
kube-system               aws-node-rww9f                                                    4m           43Mi
kube-system               aws-node-sfggf                                                    5m           42Mi
kube-system               cluster-autoscaler-7d5fd9d4f9-2bbwf                               1m           35Mi
kube-system               coredns-7d74b564bd-lzx97                                          2m           8Mi
kube-system               coredns-7d74b564bd-s7lxs                                          2m           8Mi
kube-system               kube-proxy-dqx4v                                                  1m           11Mi
kube-system               kube-proxy-l4fj6                                                  1m           12Mi
kube-system               kube-proxy-n8bpc                                                  1m           12Mi
kube-system               kube-proxy-q97cw                                                  1m           12Mi
kube-system               metrics-server-78c9d7c65f-5jjkl                                   2m           15Mi
node-exporter             node-exporter-2pfl5                                               1m           2Mi
node-exporter             node-exporter-5zcsg                                               0m           2Mi
node-exporter             node-exporter-6fptv                                               0m           2Mi
node-exporter             node-exporter-6p5r4                                               0m           2Mi
xvp                       config-api-0-0-54-60cf7961a8aa8738256e6a97dbeb375c-78c456442w42   1m           158Mi
xvp                       config-api-0-0-54-60cf7961a8aa8738256e6a97dbeb375c-78c45648h82j   1m           158Mi
xvp-disco-api-dev-sj-cc   xvp-disco-api-dev-sj-cc-0-0-54-8fcb583a40759d8d41cab54e6f1g9k5l   7m           363Mi
xvp-disco-api-dev-sj-cc   xvp-disco-api-dev-sj-cc-0-0-54-8fcb583a40759d8d41cab54e6f1jqldc   8m           346Mi
xvp-disco-api-dev-sj-cc   xvp-disco-api-dev-sj-cc-0-0-54-8fcb583a40759d8d41cab54e6f1mbr8j   7m           348Mi
```

HPA comes in two versions:

* `v1` for CPU based scaling,
* `v2` for all kinds of (custom) metrics including CPU and memory

Currently we use CPU-based scaling only with `v2`

The autoscaling formula used is `desiredReplicas = ceil[currentReplicas * ( currentMetricValue / desiredMetricValue )]`

This lets HPA schedule/remove pods itself. Cluster Autoscaler notices those scheduled pods & actually scales the worker nodes (via the ASG) to provide the actual CPU/memory power.

Follow-up documentation: [https://medium.com/devops-for-zombies/understanding-k8s-autoscale-f8f3f90938f4](https://medium.com/devops-for-zombies/understanding-k8s-autoscale-f8f3f90938f4)

### Node groups

[Service specific](https://github.com/comcast-xvp/xvp/blob/main/docs/Platform/k8s/blended-node_groups.md)

### Pod networking

EKS pods require a lot of IPs. To allow for that, we use [CNI](https://docs.aws.amazon.com/eks/latest/userguide/pod-networking.html). The important part is to have the `ENIConfig` that maps the availability zones of the Cluster's (protected rail) subnet to the private subnet that should be used where possible.

Special consideration should be made with regards to Pod networking when selecting instance sizes. AWS imposes limitations on the number of private IP address that can be allocated per network interface, which differ based on instance size. For more information, please refer to the [AWS Documentation](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-eni.html#AvailableIpPerENI).

#### TSF

In all discussions & designs, please remember the overloaded usage of the term _public_ and _private_ networks: In AWS's VPC APIs, _public_ means either "issued an IPv4 address that is owned and managed by AWS" or when talking subnets, "a subnet that contains a route through an IGW". In AWS terms _private_ (or "internal" depending on the API) means "issued an IP address from the VPC's assigned CIDR ranges, whether those addresses are technically _public_, aka "routable on the Internet-at-large" or _private_ (the way we usually mean it - 10.x RFC1918 non-Internet routable addresses). For subnets, if the default route goes through anything other than an IGW, it's considered _private_.

From a general networking / TCP-IP perspective, _public_ and _private_ usually mean whether the IP addrs are routable on the Internet or they are RFC1918 (`10.x`/`192.168.x`/`172.16.x`) addresses that must traverse a layer of NAT to reach the Internet. In TSF, the IPv4 addresses assigned to the VPC are from Internet-routable "DMZ space" that is owned and managed by Comcast. As long as firewall rules (TSF ACLs) exist to allow ingress from the Internet, that can happen, but they are reached through a Direct Connect Gateway (VGW) and the packets must traverse Comcast's routers, not directly via an Internet Gateway (IGW) on AWS's network.

But the VPC and LB APIs consider that _private_ space because AWS doesn't own it. Therefore, all EKS documentation regarding networking should be read with the _private_ glasses on!

Further documentation: [https://docs.aws.amazon.com/eks/latest/userguide/network_reqs.html](https://docs.aws.amazon.com/eks/latest/userguide/network_reqs.html)

### Prometheus scraping

The actual scraping is configured via [Lynceues](https://github.comcast.com/aae/observability-stack/). The infrastructure contains the pre-requisites:

* A service account is created to access the K8s API to use its proxy
* A bearer token is (automatically) generated & provided via Terraform's output
* A CNAME for the EKS endpoint itself is created as `xvp-shared-$env-k8s.$zone` so that the scraping config has a stable URL
* `node-exporter` is deployed to provide metrics of the EC2 worker nodes
* The existing Spring-actuator Prometheus scraper is re-used

The scraping therefore can happen by scraping via the K8s API's proxy approach not requiring us to have a full (federated) Prometheus resources within the cluster.

### SSH access

SSH access to neither the pod nor the worker are not planed at this time.

* A pod (Container) is supposed to be like a (OS) process: While technically possible, adding another process - like a SSH agent - into the container (aka. XVP image) makes a lot of things hard to use the resulting image and is against that concept in general.
* Interactive (TTY) access to a pod is already possible in [`kubectl exec`](./triage.md#general-triaging): EKS protects it via IAM. It is like `docker exec` for a running container.

* The EC2 worker node itself is considered a black box provided by AWS at this point:
  The EC2 image is provided by AWS and it doesn't contain SSH for security reasons.
  While possible, adding SSH to the base AIM involves:
  * baking our own EC2 EKS node group images,
  * secure our SSH endpoint
  * deal with the Firewall to allow SSH traffic - especially in a TSF world where such traffic is explicitly denied and requires (another) jumpbox If a worker behaves strangely it should be terminated - and the rest should be covered via regular observability patterns

* Looking even further into the future: EKS on Fargate (and getting rid of EC2 workers) won't have any SSH by design. Any process we design specifically for the EKS EC2-world would need to be re-invented.

## Kiali UI

Kiali is a management console for Istio service mesh that is installed within a EKS cluster and integrates with the Lynceus managed Prometheus stacks to visualize a XVP service's components and traffic flows. It is the first of many Observability tools that provides insights into the Istio service mesh. One can view information such as graphs on namespaces that are connected to the service mesh, traffic coming in and out of the service mesh, and many more visuals. It can also be used to triage service mesh issues as Kiali can report on the health status of Istio components (ex. ingress gateways, virtual gateways, etc.). There are two ways to access Kiali:

### Access Kiali locally

In order to access the Kiali UI you must first authenticate with AWS via `aws_adfs_auth` and update your kubeconfig to the appropriate AWS region which you would like to access. Once you perform these steps, you can run the following command which will open up the Kiali UI on your localhost:

```bash
istioctl dashboard kiali
```

which will open `http://localhost:20001/kiali` on your favorite Web Browser. It will prompt for SSO/OIDC and will take you into Kiali once you are authenticated. If you cannot access Kiali due to permission errors please reach out to the platform team to adding you to the appropriate Azure AD group tied to the WebSecDev Client ID.

### Access Kiali with Route53

Kiali can be accessed by a route53 record that works only on VPN due to a combination of TSF and other networking components. Because Kiali is deployed per cluster, it will have its own record. For example to access Kiali in `dev` us-east-1:

[`https://kiali.dev.exp.us-east-1.aws.xvp.xcal.tv/kiali`](https://kiali.dev.exp.us-east-1.aws.xvp.xcal.tv/kiali)

The format is `https://kiali.${ENV}.exp.${AWS_REGION}.aws.xvp.xcal.tv/kiali`

Note: The Prometheus credentials are stored in vault and used to access the Prometheus metrics region-specific endpoint.

More information can be found on the Kiali website [here](https://kiali.io/) and on the Istio website [here](https://istio.io/latest/docs/tasks/observability/kiali/)

### Kiali with OAuth application

Kiali urls are registered in Websec Portal to enable `Log In with OpenId` option.

Websec Portal `https://ssodevportal.cable.comcast.com/portal/#/itrc`

In websec portal we have below application created to facilitate the OpenId access.

* XvpServices - OAUTH2PROXY   (Production)
* XvpServices - OAUTH2PROXY - Dev
* XvpServices - OAUTH2PROXY - Stg

The Kiali urls are registered in `redirectURI` portion of the websec applications.

This was previously a manual step however, in Blue-Green, the new kiali urls are dynamically created during the deployment with eks version as suffix of host name. This means we have to add the new kiali url to websec portal as part of `redirectURI`

To help automate this work, as per suggestion of `websec admins` we created new application `XvpServices - OAUTHPARENT`, this application can able to access the below application.

* XvpServices - OAUTH2PROXY   (Production)
* XvpServices - OAUTH2PROXY - Dev
* XvpServices - OAUTH2PROXY - Stg

`e.g Kiali url`

* `https://kiali-v23.plat-dev.exp.us-east-2.aws.xvp.xcal.tv/kiali`
* `https://kiali-v22.plat-dev.exp.us-east-2.aws.xvp.xcal.tv/kiali`

So the terraform code use the `XvpServices - OAUTHPARENT` application client id to update all other application for different environments.
