# K8s DNS Resolution Fix

## Problem

When starting the gateway (`openshell gateway start`) the cluster fails with:

```
dial tcp: lookup registry: Try again
```

The root cause is a chain of failures triggered by an **iptables backend mismatch**:

1. `iptables v1.8.10` defaults to the **nf_tables** backend.
2. The gateway container's kernel does not expose the required nf_tables modules.
3. Every iptables rule insertion fails:
   ```
   RULE_INSERT failed (No such file or directory): rule in chain INPUT
   ```
4. **kube-router** (the k3s network-policy controller) calls `Fatalf()` on the
   first failure and panics, taking the agent process down.
5. With no network-policy controller running, inter-pod routing rules are never
   programmed, so **CoreDNS** is unreachable.
6. Any hostname lookup that goes through the cluster stub resolver returns
   `SERVFAIL` / "Try again".

## Fix

### Option 1 – k3s server config (preferred for node-level installs)

Copy `k3s-config.yaml` to `/etc/rancher/k3s/config.yaml` **before** starting k3s:

```sh
sudo mkdir -p /etc/rancher/k3s
sudo cp k8s/k3s-config.yaml /etc/rancher/k3s/config.yaml
sudo systemctl restart k3s   # or k3s-agent
```

Key settings:
- `disable: [network-policy]` – prevents kube-router from running and panicking.
- `iptables-mode: legacy` – forces the xtables backend for all k3s iptables calls.

### Option 2 – Host iptables switch (run before k3s starts)

```sh
sudo bash scripts/fix-iptables.sh
```

This calls `update-alternatives` to point all `iptables*` / `ip6tables*`
binaries at their `-legacy` variants system-wide.

### Option 3 – Init container (for pod-based gateway deployments)

Apply `k8s/gateway-init-container.yaml` as a patch to the gateway Deployment.
The init container runs before the main process and symlinks all iptables
binaries to the legacy backend within the pod's filesystem.

```sh
kubectl patch deployment <gateway> -n <namespace> \
  --patch-file k8s/gateway-init-container.yaml
```

### After applying the fix

Once iptables is using the legacy backend:
- kube-router starts successfully
- Pod network routes are programmed
- CoreDNS becomes reachable
- `lookup registry` resolves correctly
- The `openshell` namespace can be created and images can be pulled

Optionally increase CoreDNS replicas for resilience:

```sh
kubectl patch deployment coredns -n kube-system \
  --patch-file k8s/coredns-patch.yaml
```
