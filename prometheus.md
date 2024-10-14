# PROMETHEUS

![Prometheus](./img/prometheus.png)

The code for xvp-prometheus can be found [here](https://github.com/comcast-xvp/xvp-prometheus)

This repositories responsiblites end with creating a k8s service account token and pushing it to vault that xvp-prometheus uses for authentication. This code can be found in `infra/terraform/xvp-exp-common/k8s/k8s-prometheus.tf`

xvp-prometheus is a stop gap solution and will be deprecated by prometheus soon

## PROMETHEUS OPERATOR

In order to create a prometheus instance that pushes to Victoria Metrics in our EKS cluster, use the following `Prometheus` CRD for reference:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: my-prometheus-shard
  namespace: my-project
spec:
  securityContext:
    # Prometheus must set fsGroup 65534 when using ebs volume
    runAsGroup: 65534
    runAsNonRoot: true
    runAsUser: 65534
    fsGroup: 65534
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Delete
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: ebs-sc
        resources:
          requests:
            storage: 20Gi
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: prometheus
            operator: In
            values:
            - "true"
  tolerations:
  - effect: NoSchedule
    key: dedicated
    operator: Equal
    value: prometheus
  serviceAccountName: prometheus
  resources:
    requests:
      memory: 400Mi
      cpu: 500m
    limits:
      memory: 1Gi
      cpu: "1"
  podMonitorSelector:
    matchLabels:
      app.kubernetes.io/component: my-scrape-config
  remoteWrite:
  - basicAuth:
      password:
        key: password
        name: victoria-metrics-basic-auth
      username:
        key: username
        name: victoria-metrics-basic-auth
    url: https://vmauth.us.eks.monitoring.comcast.net:8427/api/v1/write
```

This will require having the basic auth for Victoria Metrics setup:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: victoria-metrics-basic-auth
  namespace: my-project
spec:
  data:
  - remoteRef:
      key: xvp/k8s-secrets/metrix/<env>/<region>
      property: remote_write_user
    secretKey: username
  - remoteRef:
      key: xvp/k8s-secrets/metrix/<env>/<region>
      property: remote_write_password
    secretKey: password
  refreshInterval: 10m
  secretStoreRef:
    kind: ClusterSecretStore
    name: vault-backend-v2
  target:
    name: victoria-metrics-basic-auth
```

Then in order to have a scrape config use either a `ServiceMonitor` or `PodMonitor`, example:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: my-project
  namespace: my-project
  labels:
    app.kubernetes.io/component: my-project
spec:
  selector:
    matchLabels:
      app.kubernetes.io/component: my-project
  podMetricsEndpoints:
    - port: metrics
      path: /metrics
```

These CRDs are highly configurable, please see [prometheus operator](https://prometheus-operator.dev/) docs for more information

## Shards

Sharding prometheus is breaking out the scrape jobs into separate prometheuses in order to better scale prometheus.

### Istio

There is a prometheus that scrapes all istio based metrics in `infra/terraform/xvp-exp-common/k8s/k8s-observability-metrics.tf`.

#### Add new namespace to scrape

In order to scrape a new namespace for that's istio related, add it to the namespaceSelector in the `istio-metrics` pod monitor.

#### Scrape new pods

In order to scrape new pods, first make sure the pods have the `app.kubernetes.io/component` label and then add it to the values section of the selector in the pod monitor.

#### Allow a metric

In order to allow a metric for istio scraping add look for the `# Allow list metrics` comment and add it to the list of metrics below it. See how [relabel config](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#relabel_config) works in prometheus for more info
