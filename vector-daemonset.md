# What is Vector?

Vector is an observability data pipeline that facilitates the collection, processing, transformation, and routing of logs, metrics, and traces. XVP uses Vector to send logs to [ELK](https://internal-xvp-docs-staging.r53.aae.comcast.net/Support/Playbooks/elk/elk/) and [Backwaters](../docs/titan-backwaters.md). To read more about Vector, visit [here.](https://vector.dev/docs/about/concepts/)

## Vector as a daemonset

Vector is deployed as a [daemonset](https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/). Essentially, this means that all Nodes run a copy of the Vector pod. This can be helpful for tasks like node monitoring or (in the case of Vector) logs collection. Currently, Vector configuration is stored in both xvp-infra-core and comcast-observability-tenants//xvp.

## Important note about daemonsets

As of this writing, daemonsets have 2 types of [update strategy](https://kubernetes.io/docs/tasks/manage-daemon/update-daemon-set/#daemonset-update-strategy). **RollingUpdate is the default.**

OnDelete: This strategy ensures that new DaemonSet pods will only be created after you have manually deleted the old DaemonSet pods

RollingUpdate: After deploying a change to daemonset configuration, old pods will be killed and new pods will spin up in a controlled, configurable manner.
