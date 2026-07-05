# Load balancing: client-side vs server-side (talk reference)

A speaker's cheat-sheet for stage **03 (load balancing)**. The question the lab raises is *where
does the "which node gets this request?" decision live?* There are two answers, and real systems
use both.

> **Where this lab sits:** the scalability ladder (00–04) does **client-side** load balancing —
> the decision lives in [`load_balancer.py`](diffs/README.md), a library `client.py` imports, and
> the nodes know nothing about each other. The cluster stages (05–10) move the decision **out to a
> server-side component** — the gateway (`:8000`) and coordinator (`:7000`). So the workshop itself
> walks the room from one model to the other.

---

## The two models in one picture

```
CLIENT-SIDE                                SERVER-SIDE
(smart client picks a backend)             (dumb client, a proxy picks the backend)

  client ──┐ get_node()                      client ──► [ LB / proxy ] ──┬──► node
           ├──► node                                                     ├──► node
           ├──► node                                                     └──► node
           └──► node

  decision: in the client                    decision: in a dedicated process
  hops to backend: 1 (direct)                hops to backend: 2 (via the LB)
```

---

## Client-side load balancing

The client holds the list of backends and chooses one itself (usually with a service-discovery
registry feeding it the membership). No middlebox in the data path.

**Real systems**
- **gRPC** built-in LB (`pick_first`, `round_robin`, and xDS-driven policies).
- **Finagle** (Twitter/X) — client-side LB with power-of-two-choices and "deterministic aperture".
- **Netflix Ribbon** + **Eureka** (classic JVM stack); its successor **Spring Cloud LoadBalancer**.
- **Database / KV drivers** — the most relevant to *this* lab:
  - **Cassandra / ScyllaDB** drivers: *token-aware* routing — the client hashes the key and sends
    it straight to the replica that owns it.
  - **Redis Cluster** clients: the client computes the hash slot and connects to the owning node.
  - **MongoDB** drivers: pick a healthy member per read-preference.
- **Kafka** producers: the partitioner picks the partition (hence the broker) client-side.

**Pros**
- **No extra hop** → lower latency, and no proxy to pay for or operate.
- **No central bottleneck / SPOF** in the data path — capacity scales with the clients.
- **Rich local signal** — the client knows its *own* in-flight requests and observed latencies, so
  least-loaded / power-of-two routing is naturally good (this is exactly our `AdaptiveStrategy`).

**Cons**
- **Logic in every client, in every language** — polyglot fleets re-implement it N times.
- **Clients need discovery** and must handle membership churn (nodes joining/leaving) themselves.
- **Policy changes mean redeploying clients** — slow to roll out a routing fix.
- **Weak central control** — security boundary, TLS termination, global rate limiting and
  observability are all harder when the decision is spread across many clients.
- **Stale/independent views** → many clients can stampede the same "best" node (herd effect);
  power-of-two-choices exists largely to blunt this.

---

## Server-side load balancing

A dedicated component sits between clients and backends. Clients are simple ("just hit the VIP");
the proxy owns routing, health checks, and often TLS, rate limiting, and WAF.

**Real systems**
- **Reverse proxies:** Nginx, HAProxy, Envoy (standalone), Traefik.
- **Cloud LBs:** AWS ELB/ALB/NLB, GCP Cloud Load Balancing, Azure Load Balancer / App Gateway.
- **Hardware:** F5 BIG-IP, Citrix ADC (NetScaler).
- **Kubernetes:** `kube-proxy` (iptables/IPVS) for Services + an Ingress controller for L7.
- **Hyperscale L4:** Google **Maglev**, Meta **Katran**.
- **Global (GSLB / DNS / anycast):** Route 53, Cloudflare, Akamai — "which *region*?" before
  "which *node*?".

**L4 vs L7 (worth a sentence on stage):** L4 (e.g. AWS NLB, Maglev) balances TCP/UDP connections —
fast, content-blind. L7 (e.g. ALB, Nginx, Envoy) understands HTTP, so it can route by path/header,
terminate TLS, retry, and rate-limit — at higher cost per request.

**Pros**
- **One place for policy** — routing, TLS, rate limiting, canary, WAF, metrics all centralized.
- **Dumb, language-agnostic clients** — nothing to re-implement per language.
- **Strong control point** — hide backend topology, enforce security, get uniform observability.

**Cons**
- **Extra network hop** → added latency.
- **The LB must itself be made HA and scaled** — done badly it's a bottleneck and a SPOF; done well
  it's more infrastructure to run (and pay for).
- **Less per-client context** than a smart client has (it sees backend health, not each client's
  in-flight load), though good L7 LBs track backends closely.
- **Centralized blast radius** — an LB misconfig can take everything down at once.

---

## Hybrid: the service-mesh / sidecar model

Modern meshes split the difference: a **control plane** sets policy centrally, while a **sidecar
proxy next to each client** (Envoy in **Istio**, the Linkerd2 micro-proxy) makes the actual
per-request decision locally.

- **Examples:** Istio/Envoy, Linkerd, Consul Connect; gRPC **lookaside** LB (an external LB server
  tells the client which backends to use, client connects directly).
- **Why:** you get centralized, hot-reloadable policy (server-side win) *and* a local, low-context-
  loss decision one hop from the client (client-side win).
- **Cost:** a proxy per workload to run and observe — real operational complexity.

---

## How to map it back to the lab (one-liner for the room)

> "In stages 01–04 the **client** is smart and the nodes are dumb — that's client-side load
> balancing, like a Cassandra or Redis Cluster driver. As we build the real cluster in 05–10, the
> smarts move **out of the client and into the gateway and coordinator** — that's the shift to
> server-side. Neither is 'correct'; you're trading an extra hop and a central control point
> against duplicated client logic and a weaker security boundary."
