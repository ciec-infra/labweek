# Kubernetes Event-Driven Autoscaling (KEDA)

KEDA is a single-purpose and lightweight autoscaler that extends the functionality of the Kubernetes Horizontal Pod Autoscaler (HPA) and can be used to facilitate scaling based on a variety of event sources such as CPU, memory, Prometheus, and more. You can read more about KEDA [here](https://keda.sh/).

KEDA has 3 roles in a cluster:

1. Agent: This is performed via the keda-operator container which handles deployment scale-in/out
2. Metrics: The keda-metrics-apiserver container acts as a Kubernetes metrics server and exposes data to the HPA
3. Admission webhooks: Enforce best practices and prevent misconfigurations such as having multiple ScaledObjects mapped to the same target

## Scaled Objects

Scaling can be achieved via Scaled Objects or Scaled Jobs, but most commonly the former. Scaled Objects target one of: Deployments, StatefulSets, or Custom-Resource Definitions (CRDs).

## KEDA in XVP-Infra-Core

Previously, the scaling of the Istio-Ingress-Gateway and Istio-East-West-Gateway were both managed by the HPA (configured in their respective helm charts). This configuration controlled min replica count, max replica count, and CPU Utilization target scaling. This has been moved to [k8s-istio.tf](https://github.com/comcast-xvp/xvp-infra-core/blob/main/infra/terraform/xvp-exp-common/k8s/k8s-istio.tf) under the "keda-scaled-igw-pods" and "keda-scaled-ew-gateway-pods" kubectl manifests. The trigger for CPU Utilization is set via a local variable because this value is consistent among regions/environments. Currently the only additional trigger being used is cron scaling, but more can be added as needed.

## KEDA-based Cron Scaling for XRE Traffic

XRE runs load-tests from 7am to 11am UTC, so to better accomodate this increased traffic (in US Prod), the Istio-Ingress-Gateway scales up at 6:40am and back down at 11:15am via the ingress_cron_triggers variable. The cron trigger is a list variable that by default is empty, and will only be applied if one has been set in the respective region/cluster terraform.tfvars (e.g, prod/us-east-2). Using a variable for this trigger allows granularity across regions and environments; each cluster can have their own unique cron trigger(s).

## Multiple Cron Triggers

Our KEDA configuration supports multiple IGW cron triggers. Adding additional triggers is straightforward (see below):

```terraform
ingress_cron_triggers = [
  # XRE Reboot
  {
    "timezone"        = "UTC"
    "start"           = "40 06 * * *"
    "end"             = "15 11 * * *"
    "desiredReplicas" = "30"
  },
  # Superbowl
  {
    "timezone"        = "UTC"
    "start"           = "30 22 * * *"
    "end"             = "00 03 * * *"
    "desiredReplicas" = "50"
  }
]
```

The KEDA docs do not specify a limit to the number of cron triggers that can be tied to a ScaledObject.

## KEDA-based metric based request scaling

We added the ability for our istio-ingress gateways to scale based on the number of request. This feature has been created to work in conjunction with ingress pod level rate limiting. This to ensure we will always be scaling before we rate limit & we would always want ingress_keda_autoscaling_rps_rate to be set lower the our rate limit. Some notes Keda looks at the metric every 30 seconds looking at istio reqeust total for the ingress over a second time to see the total number of istio ingress request and then divides it by the number of replicas. So as an example if ingress_keda_autoscaling_rps_rate is set to 2275 that means it will scale when the istio total request for ingress/number of replicas is 2275 * 1.1 (HPA Tolerance [further details](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/#algorithm-details) ) = 2502.5 RPS it will scale as much as needed to meet demand.

## FAQ

### Resolving discrepancies

An important question that is brought up often in discussions on KEDA, is how does KEDA manage discrepancies between triggers? What if a cron trigger is planning to scale up while a CPU trigger is planning to maintain the same replica count? The answer to this question is always that KEDA will scale based on the highest replica count, whether the discrepancy is between 2 cron triggers or 2 different triggers.

### Can I use KEDA (ScaledObject) and HPA at the same time?

Per KEDA documentation, HPA is used under the hood (KEDA modifies its own HPA to perform its functions), so attempting to use both is, in essence, attempting to use 2 HPAs at the same time, which will likely result in unexpected scaling behavior. This is not recommended.

### What happens if KEDA can't retrieve metrics? (e.g., Prometheus is down)

Currently, xvp-infra-core does a external metrics-based scalers in its KEDA configuration. However there is no concerns if it is unable to reach our metric stack it will scale to the min and let cpu scaling take over

KEDA offers a fallback configuration block for situations where a scaler is in an error state. If specified, when a scaler enters an error state the number of replicas will fall back to the number described in this section. Note that this only supports scalers using an **AverageValue** target metric (disabled for CPU/Memory scalers). Also note that this is only supported by Scaled Objects not ScaledJobs.
