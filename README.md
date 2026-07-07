# Deconstructing the tenets of Planet Scale Systems with Python

> _"There are only two hard problems in distributed systems: 2. Exactly-once delivery 1. Guaranteed order of messages 2. Exactly-once delivery"_

If this made you curious, this tutorial is the right place to dive deeper into the interesting (sometimes weird) world of Distributed Systems.

When you think of constructing systems that can scale to billions of people, you have to think beyond single node programming patterns. This introduces a couple of intriguing challenges like how do you make thousands of nodes agree? Or jargons like _CAP Theorem_. To make matters even more complicated, most of the material on this subject is highly theoretical & geared towards advanced learners. This quickly discourages a lot of programmers who tend to learn better by doing rather than just reading about things.

Python has always been a great vehicle to learn complex technologies efficiently. It enables a programmer to cut through the weeds to focus on the core concepts. This was recently exemplified when Andrej Karpathy taught a way to train a GPT in pure python with [microgpt.py](https://programme.europython.eu/redirect/?url=https%3A//gist.github.com/karpathy/8627fe009c40f57531cb18360106ce95%3AgnNfAsWrFlNaFcJrVgUh9Xt-LbRYxfJkrx4lM7KohWs).  
Similarly, it can be an efficient vehicle to deconstruct the fundamentals of large scale systems, which are essential for a holistic view of modern day applications.

In this tutorial, we will have several hands on exercises to dive deeper into the tenets of reliability, availability & scalability. By simulating a Distributed Cluster with pure python code we'll poke the system, make it fail & closely study the perils of planet scale systems & how to overcome them.

Towards the end of the tutorial, you'll have a clear mental model of some of the most confusing concepts in distributed systems. The ultimate goal is to give you enough knowledge, curiosity & tooling so that you can explore this field on your own & be confident about building the next planet scale system.

## Quick setup

> **Do this once, on a good internet connection, _before_ the workshop.** The first build downloads
> a base image and dependencies (a few minutes) — you don't want to fetch that over conference WiFi.

### 1. Install Docker
You need **Docker with Compose v2** (the `docker compose` command). Pick your OS:
- **macOS** — install **Docker Desktop**.
- **Windows** — install **Docker Desktop** (WSL2 backend). Run every command below from
  **PowerShell** or a **WSL2 Ubuntu** shell — **not Git Bash** (it breaks `docker compose exec`).
- **Linux** — install **Docker Engine** + the **Compose plugin** (`docker-compose-plugin`); Docker
  Desktop is not required.

_Please note that due to limited bandwidth, I'll not be able to assist into Docker installation during the workshop._

### 2. Build and start the workshop
```bash
git clone https://github.com/abhimanyu-bitsgoa/europython-planetscale-systems.git
cd europython-planetscale-systems
docker compose up -d                 # build + start the container (first run takes a few minutes)
docker compose exec workshop bash    # open a shell inside it — everything below runs in here
```
### 3. Verify it works
Inside the container shell:
```bash
make verify    # ~15s preflight: checks the toolchain and boots a real node
make start     # seed your working copy from the first checkpoint
```
`make verify` should finish with every check passing and print **`SETUP VERIFIED`**.
Once you see that, you're ready. A successful run looks like this:

![A successful `make verify` run — every check shows [OK] and the "SETUP VERIFIED" box appears](verify.png)

If anything looks off, reset and retry: `exit`, then `docker compose down && docker compose up -d`.

Once you are done with the verification, kindly mark your completion [here](https://forms.gle/ztp98S4u1tGK7dCC9). This will help me plan better.

You are all set for the workshop.

Feeling excited? Take a look at the **[LAB-MANUAL.md](LAB-MANUAL.md)** to get a taste of what we'll be doing.

