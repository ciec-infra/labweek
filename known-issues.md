# Known Issues

This doc will cover all know issues related to our xvp-infra-core-repo. Known issues are issues that can not or should not be fixed. Please try
and have any upstream documentation ex. github issue to track if this fixed in the future

## Hashicorp/Helm Provider

We have a known issue with hashicorp helm issue that the provider does not update the CRD when updating the version of the helm chart. This can be
mitigated in one two ways the resource is updated during blue green so it is installed freshly or the resource is renamed so it can be recreated.
If you do the latter please be sure that change is not disruptive and will not have any impact

[Upgrading CRD github issue](https://github.com/hashicorp/terraform-provider-helm/issues/944)
