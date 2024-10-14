# Pushing Istio Ingress-Gateway Logs to ELK

## Goal

Get the istio ingress-gateway logs using vector agent and transfrom istio logs fields to appropriate ECS fields; and sink them to Kibana.

## Overview

Each istio gateway log has 24 different fields. Most of them were mapped to appropriate ECS fields; and field that doesn't have an appropriate ECS field have a custom name.

### Istio field => ECS/Custom field

| Istio field Name | ECS field Name | Custom Field Name |
| ---------------- | -------------- | ----------------- |
| START_TIME | @timestamp | |
| METHOD | http.request.method | |
| X-ENVOY-ORIGINAL-PATH?:PATH | url.original | |
| PROTOCOL | network.protocol | |
| RESPONSE_CODE | http.response.status_code | |
| RESPONSE_FLAGS | not found | envoy.response_flags |
| RESPONSE_CODE_DETAILS | http.response.body.content | |
| CONNECTION_TERMINATION_DETAILS | not found | enovy.connection_termination_details |
| UPSTREAM_TRANSPORT_FAILURE_REASON | event.reason | |
| BYTES_RECEIVED | http.request.body.bytes | |
| BYTES_SENT | http.response.body.bytes | |
| DURATION | event.duration | |
| RESP(X-ENVOY-UPSTREAM-SERVICE-TIME) | not found | envoy.upstream_service_time|
| REQ(X-FORWARDED-FOR) | client.ip | |
| REQ(USER-AGENT) | user_agent.original | |
| REQ(X-REQUEST-ID) | http.request.id | |
| REQ(:AUTHORITY) | url.domain | |
| UPSTREAM_HOST | not found | envoy.upstream_host |
| UPSTREAM_CLUSTER | not found | envoy.upstream_cluster |
| UPSTREAM_LOCAL_ADDRESS | not found | envoy.upstream_local_address |
| DOWNSTREAM_LOCAL_ADDRESS | destination.address | |
| DOWNSTREAM_REMOTE_ADDRESS | source.address | |
| REQUESTED_SERVER_NAME | tls.client.server_name | |
| ROUTE_NAME | not found | envoy.route_name |

### Additional fields in the kibana

| ECS Name | Custom Name | Description |
| -------- | ----------- | ----------- |
| | orchestrator.cluster.name | Gives name of the cluster, eg. xvp-eks-dev-v76 |
| | envoy.gateway_type | What type of gateway, eg. ingress, egress or east-west |
| service.environment | | Gives info about envs, eg. plat-dev, dev, prod, stg |
| service.name | | Name of the service, eg. disco, linear etc. |
| url.port | | Gives info about service port. For example, 44301. |
| orchestrator.resource.ip | | Kubernetes pod ips |
| orchestrator.resource.name | | Kubernetes pod name |
| | orchestrator.node.name | Kubernetes node name |

### Note on url.port/service port

As of today(9/22/2023), following configuration is used to get url port from the logs:

```text
if (contains(.url.domain, ":")){
      .url.port = split(.url.domain, ":")[-1]
    }
```

**Concern:** This configuration doesn't always give info about url.port. It would better if we use the following configuration on our future deployment to get url.port info most of the time.

```text
if (contains(.destination.address, ":")){
      .url.port = split(.destination.address, ":")[-1]
    }
```

### Details about some of the response flags given below

| Response_flags | Description |
| -------------- | ----------- |
| UH | No healthy upstream hosts in upstream cluster in addition to 503 response code. |
| UF | Upstream connection failure in addition to 503 response code. |
| UO | Upstream overflow (circuit breaking) in addition to 503 response code. |
| NR | No route configured for a given request in addition to 404 response code, or no matching filter chain for a downstream connection. |
| URX | The request was rejected because the upstream retry limit (HTTP) or maximum connect attempts (TCP) was reached. |
| NC | Upstream cluster not found. |
| DT | When a request or connection exceeded max_connection_duration or max_downstream_connection_duration. |

In order to get more details about the isttio fields [please follow this LINK](https://www.envoyproxy.io/docs/envoy/latest/configuration/observability/access_log/usage)

### Vector and Index configuration

1. Name of the kibana space **XVP Istio Gateway** [LINK](https://github.com/comcast-observability-tenants/xvp/tree/main/es/kibana/xvp-istio-gateway)
2. Name of the elasticsearch index **logz-istio-gateway_index** [LINK](https://github.com/comcast-observability-tenants/xvp/blob/main/es/indices/logz-istio-gateway.index)
3. Name of vector config file **igw.toml** [PR](https://github.com/comcast-observability-tenants/xvp/pull/182)
4. Name of istio gateway component template **logz-istio-istiod-mappings.component** [LINK](https://github.com/comcast-observability-tenants/xvp/blob/main/es/indices/logz-istio-istiod-mappings.component)

### Why igw.toml doesn't have unit test

`.service.environment = slice!(.kubernetes.node_labels.component, 9)` this line breaks our unit test as it tries to slice a field that doesn't exists.

In case anyone wants to see the unit test; to make the unit test work, we need to comment out the line `.service.environment = slice!(.kubernetes.node_labels.component, 9)`. [This commit](https://github.com/comcast-observability-tenants/xvp/pull/182/commits/fb6d5f50d2183426fb4bddc37d6723969013e0be) makes the unit test work while the specific line is commented out.

### Egress and East-West gateway configuration

To get Egress and East-West gateway logs, use this `extra_label_selector = "app in (istio-ingress, istio-eastwestgateway, istio-egress)"` instead of `extra_label_selector = "app=istio-ingress"` in out [igw.toml file](https://github.com/comcast-observability-tenants/xvp/blob/main/vector/xvp-eks/igw.toml) like this [Test PR](https://github.com/comcast-observability-tenants/xvp/pull/223); and make sure to validate each fields(specifically for east-west gateway logs) are giving as same info as ingress-gateway logs. This [Slak conversation might be helpful](https://cim.slack.com/archives/C02N48X67AM/p1692303932704739)

### Errors

1. This [PR and it's comment](https://github.com/comcast-xvp/xvp-infra-core/pull/988) gives info about some of the errors we had during the whole effort.
2. There were some existing errors, one of them is:

```text
2023-08-15T08:59:14.260863Z ERROR sink{component_kind="sink" component_id=istio_ingress_logs component_type=elasticsearch component_name=istio_ingress_logs}:request{request_id=4682}: vector::sinks::util::retries: Not retriable; dropping the request. reason="error type: cluster_block_exception, reason: index [logz-istio-gateway-000010] blocked by: [TOO_MANY_REQUESTS/12/disk usage exceeded flood-stage watermark, index has read-only-allow-delete block];" internal_log_rate_limit=true
2023-08-15T08:59:14.260903Z ERROR sink{component_kind="sink" component_id=istio_ingress_logs component_type=elasticsearch component_name=istio_ingress_logs}:request{request_id=4682}: vector_common::internal_event::service: Service call failed. No retries or retries exhausted. error=None request_id=4682 error_type="request_failed" stage="sending" internal_log_rate_limit=true
2023-08-15T08:59:14.260919Z ERROR sink{component_kind="sink" component_id=istio_ingress_logs component_type=elasticsearch component_name=istio_ingress_logs}:request{request_id=4682}: vector_common::internal_event::component_events_dropped: Events dropped intentional=false count=53 reason="Service call failed. No retries or retries exhausted." internal_log_rate_limit=true

```

We connected with #observability-logging-support team on this regard. [Here's the slack conversation](https://cim.slack.com/archives/CAM4CRM41/p1692107876720369), and [Here's the ticket](https://ccp.sys.comcast.net/browse/OOL-678) we created on 8/15/2023. After following up with them couple time didn't give us any resutl, and on 9/19/2023 they put this on hold with the following message.

```text
Wayda, William : We have a US in backlog, due to the priorities we are not able to complete this request at the moment. We are monitoring this cluster manually although. We need to put this ticket on hold.

Thanks,
Ramesh

```
