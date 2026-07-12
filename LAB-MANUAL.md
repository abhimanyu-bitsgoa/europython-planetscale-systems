# Lab Manual

You'll build a distributed key-value store from a single Python `dict` behind HTTP into a
fault-tolerant cluster, one stage at a time. Every stage gives you a live dashboard to
poke the system by hand and watch it react.

This is the follow-along spec for the workshop.

## The ladder

Each stage adds one idea;  The four ✏️ stages ask you to write some code — the rest are run-and-explore.

| # | Stage | What you learn | ✏️ |
|---|---|---|---|
| 01 | Single Node | A KV store is a dict behind HTTP | |
| 02 | Vertical Scaling | Sometimes, adding more resources is right | |
| 03 | Horizontal Scaling & Load Balancing | Using multiple nodes to scale the Compute | ✏️ |
| 04 | Rate Limiting | Protecting your node from abuse | ✏️ |
| 05 | Replication | Basics of Single Leader Replication | ✏️ |
| 06 | Synchronous Replication | Consequences of writing to all followers | |
| 07 | Quorum & CAP Theorem | Simple understanding of CAP Theroem | |
| 08 | Service Discovery | How to detect a node outage | ✏️ |
| 09 | Auto recovery | Get a node up & catchup | |
| 10 | Full System | The whole thing behind a gateway | |

---

## Setup

Install Docker, build the container, and verify it works by following the
**[Quick setup in the README](README.md#quick-setup)** — do this once before the workshop.

---

## How a stage works

**1. Load the stage into your working copy (`kvstore/`).**

```bash
make todo STAGE=NN         # ✏️ code stages (03/04/05/08): loads the exercise with one blank function
make checkpoint STAGE=NN   # any stage: loads the complete, working code (also your "rescue" button)
```
**2. Interactive way**

```bash
make lab STAGE=NN          # This starts the interactive lab
make lab-dowb              # Use this to exit the interactive shell
```

One window, several panes: a **service pane** per process (nodes, or registry / coordinator /
gateway) so you watch them react; a **control pane** pre-loaded with helper commands (it prints its
own command list when it opens); an **incident pane** with the check pre-typed; and a **scratch**
shell. Mouse mode is on — click a pane to focus, scroll to read history. Tear it down with
`make lab-down`.

**3. Incidents**

The **incident pane**, is for checking whether the code exercises are working as expected.


_If you don't prefer TMUX shells, run `make up STAGE=NN` in one shell and
`make incident STAGE=NN` in another._

_If you are attending this workshop in EuroPython 2026, the instructor will take you along these stages incrementally._

---

## Stage 01 - Single Node

Simplest key-value store: a Python `dict` behind HTTP.

```bash
make checkpoint STAGE=01
make lab STAGE=01
nwrite status pending   # Putting "pending" as the value for key "status"
nread status            # Reading the value of key "status"
make incident STAGE=01  # Just a simple check to see client-server are working
```

## Stage 02 - Vertical Scaling

The load on your service resources (CPU, RAM, DISK etc) will rise as your users increase.
The simplest thing will be to get a more powerful machine.
Here for the lab, the `WORKERS` will denote the unicorn processes that are running the FAST API
app. Each python process will have lock contention due to GIL.
Getting more processes up so that the OS can schedule it on more cores is a loose example of how we are utilising the node more.

```bash
make checkpoint STAGE=02
make lab STAGE=02 WORKERS=1
make incident STAGE=02
```

You may notice that the incident is active & mentioned that your p95 is too slow.
Try running it with `WORKERS=4` to ease up the load on just 1 python process.

```bash
make lab STAGE=02 WORKERS=4
make incident STAGE=02
```

You'll notice that the incident is resolved now as the p95 becomes better.

_Note that depeneding upon your local machine configuration, the latency numbers might look different for you & even may not budge significantly. Instructor can take a look at your special cases after the workshop._

## Stage 03 - Horizontal Scaling & Load Balancing  ✏️

Even a powerful node is still a single point of failure. Let's think about getting more nodes to support the increasing traffic.

Since these nodes can be heterogeneous (different types, power etc) we should think more deeply about how we want to route our traffic. A blind round-robin might not always be a the best idea.

_Exercise: Take a look at `AdaptiveStrategy.get_node` in `kvstore/load_balancer.py` & complete the function._

```bash
make todo STAGE=03        # Load the code skeleton to complete
make checkpoint STAGE=03  # Load the complete code
make lab STAGE=03         # Start the interactive lab
```

You can fire the below command from the  *control panel* compare how different load balancing strategies work for your case. Based on your machines, you may see varied results. Based on the repeated runs, you can ascertain the strategy you want to adopt for the service & traffic pattern.

  ```bash
  nload round_robin 96 12   # blind 1/3 share lands on the weak node
  nload adaptive   96 12    # Tries to route to nodes that have the better chance of getting faster response
  ```

You can even choose to run a comparison between round-robin & adaptive by using 'make incident STAGE=03`

## Stage 04 - Rate Limiting  ✏️

Load balancing shares load; it doesn't *cap* it. A burst or a bad actor can still overwhelm a node. You'll implement a fixed-window limiter that sheds excess requests & returns `429` error code.

_Exercise: Complete the function `FixedWindowStrategy.is_allowed` in `kvstore/rate_limiter.py`_

```bash
make todo STAGE=04        # Load the code skeleton to complete
make checkpoint STAGE=04  # Load the complete code
make lab STAGE=04         # Start the interactive lab
make incident STAGE=04    # You'll see the requests getting rate limited
```

## Stage 05 - Replication  ✏️

Let's thing about Stateful systems now. How do we scale them?
Consider a **1 leader** & **3 followers**, coordinated by a `coordinator`. In this design the WRITES are sent to the Coordinator & then the Leader while the READS are sent to Coordinator & the Followers. The Leader is not in the READ path. This is just for simplicity.

_Exercise: Take a look at `replicate_to_follower(...)` in `kvstore/node.py` & complete the function._ 

```bash
make todo STAGE=05        # Load the code skeleton to complete
make checkpoint STAGE=05  # Load the complete code
make lab STAGE=05         # Start the interactive lab
make incident STAGE=05    # Check if your changes are working fine.
```

Let's simulate an interesting case in this cluster. Let's try reading a key a key quickly right after we write it & see if it return the latest value.

```bash
kvwrite order pending     # Setting the value of key "order" to "pending"
kvwrite order done        # Changing the value of "order" to "done"
kvread order              # If you read fast enough, you'll see a Stale value
```
Please note that for simplicity our cluster reads are happening via pre determined nodes, in the real world, we'll like to send an ACK to arbitrary number of nodes & wait for the number of ACKs we care about.

## Stage 06- Synchronous Replication

You just watched a stale read: at `W=1, R=1` the read lands on an async follower that hasn't caught
up. Turn the knob the other way  make **every** follower synchronous (`W = N`), so a write reaches
all of them before it returns. No follower can lag, so no read is stale.

```bash
make checkpoint STAGE=06
make lab STAGE=06
kvwrite order paid
kvread order
```

Let's try to remove a node from the cluster & see if we can still WRITE or READ.

```bash
kvkill 1
kvwrite order delivered
kvread order
```
Although we can still READ but WRITE is blocked. This is expected as we wanted 3 followers (excluding leader) to return an ACK for every write.
Seems like our cluster can't even tolerate the downtime of 1 follower.
So even though the data will remain consistent but the price we pay is availability & system is not fault tolerant.

## Stage 07 - Quorum & CAP Theorem

All-sync gives fresh reads but tolerates **zero** failures. The sweet spot is a **majority quorum**
(`W=2, R=2` with `N=3`): it survives 1 follower failure & reads are still fresh. When the quorum is lost, the system refuses writes to preserve consistency.

```bash
make checkpoint STAGE=07
make lab STAGE=07
kvwrite order paid
kvkill 1
kvwrite order shipped       # WRITE goes through as WRITE quorum is not lost
kvread order                # READ goes through as READ quorum is not lost
```

> `kvkill` is like a planned removal of node from the cluster. So the coordinator is aware about the node being down (As we asked it to remove it!). What happens when the nodes, just dies?

## Stage 08 - Service Discovery  ✏️

Real nodes could **crash** abruptly, telling no one. The coordinator has no health monitor, so a crash
is invisible & it keeps routing to a dead node. We can fix this by asking the nodes to send a **heartbeat** periodically to a central **registry** service.

```bash
make todo STAGE=08
make lab STAGE=08
kvwrite order paid
kvcrash 1                   # Crashing the Follower 1
kvread order shipped        # The Coordinator is not receiving write ACK anymore
kvstatus                    # Notice that Coordinator feels all the nodes are ALIVE
```
_Exercise: Take a look at `heartbeat_loop(...)` in `kvstore/node.py` & complete the function._

```bash
make checkpoint STAGE=08
make lab STAGE=08
kvwrite order paid
kvcrash 1                   # Crashing the Follower 1
kvread order shipped        # The Coordinator understands that a nodes is down
kvstatus                    # Coordinator knows about a dead node.
```
_Please note that in real systems, the Coordinator would have sent the WRITE to all the followers & would have been fine as long as it receives 2 ACKS here.
However, for the sake of simplicity, we are expecting ACKs from specific nodes only._

## Stage 09 - Auto Recovery

The next step of detecing a node outage is mitigation. The Cluster shall spin up a new node & catch it up with all the data that other nodes & the leader has.

```bash
make checkpoint STAGE=09
make lab STAGE=09
kvwrite order paid
kvcrash 1                   # Crashing the Follower 1

# Wait ~10s — the registry auto-spawns a replacement; the coordinator pane shows the catch-up

kvstatus                    # Cluster auto heals & has the data
kvread order                # The revived node has the data
```

## Stage 10 - Full System

An **edge gateway** in front of everything ties the whole system together. There's no exercise and no
check — it's the synthesis of stages 01–09, and the way to experience it is to drive it yourself.

- **Run:** `make lab STAGE=10` (registry + coordinator + gateway panes)
- **Take it for a spin (control pane):**
  ```bash
  kvwrite order pending       # trace it: gateway (:8000) → coordinator (:7000) → leader → followers
  kvread order
  kvflood 15               # hammer the edge — the rate limiter sheds the overflow as 429s
  kvwrite order paid
  kvcrash 1                # unannounced crash — quorum holds, then it auto-respawns and catches up
  kvread order             # still fresh
  ```
- Tear it down with `make lab-down`.

> Easter Egg:  Run `curl -s http://localhost:8000/graduate` from the free shell in Lab 10
---

## Cheat sheet

```bash
make verify                # preflight: check your setup end-to-end (run once before the workshop)
make start                 # seed your working copy (once, at the very beginning)
make todo STAGE=NN         # load a ✏️ code stage's exercise (03/04/05/08)
make checkpoint STAGE=NN   # load a stage's complete, working code (also the rescue button)
make lab STAGE=NN          # the dashboard: explore the stage by hand (loads non-code stages for you)
make lab-down              # tear the dashboard down
make incident STAGE=NN     # run a stage's check on its own (or press Enter in the lab's incident pane)
make status                # show your progress across the ladder
```

The typical loop: **code stage** → `make todo` → `make lab` → edit the one function → `make lab-down`,
`make lab` → press Enter in the incident pane. **Run-and-explore stage** → `make lab` → poke it →
press Enter in the incident pane.

---

## If something breaks

```bash
make lab-down            # tear down the dashboard + all its processes
make down                # stop any stray workshop processes
docker compose restart   # last resort: restart the whole container
```

If a stage won't start because a port is busy, it's almost always a leftover process from a previous
stage — `make lab-down` (or `make down`) clears it. If you've tangled up a stage's code, jump back to
a known-good state with `make checkpoint STAGE=NN`.

### Windows: `make lab` fails with "invalid option name: pipefail"

This is a line-endings mismatch. Windows Git rewrites files with CRLF (`\r\n`) on clone; the Linux
container's `bash` then sees a trailing `\r` on every line and rejects it as an unknown option.

The repo ships a `.gitattributes` that forces LF on checkout, so this should not happen on a fresh
clone. If you cloned before that file existed (or your Git ignored it), fix it once inside the
container:
```bash
find /workspace -name '*.sh' | xargs dos2unix
```

Then re-run your `make` command — it will work.

For a permanent fix so you never have to run this again on future pulls — run these on your **Windows
machine** (not inside the container), after pulling the `.gitattributes` commit:

```bash
git pull                   # get the .gitattributes commit if you haven't already
git rm --cached -r .       # wipe Git's index so it re-reads every file
git reset --hard           # re-checkout everything, now normalized to LF
```

This makes Git on Windows permanently honour the repo's LF policy for every future pull.
