STAGE ?= 01
CP := $(shell ls -d checkpoints/$(STAGE)-* 2>/dev/null | head -1)

.PHONY: help verify start todo up lab lab-down down incident checkpoint status validate snapshot

help:
	@echo "Build-a-KVStore — workshop commands"
	@echo "  make verify             preflight: check Docker/Python/tmux + boot a node (run once before the workshop)"
	@echo "  make start              seed kvstore/ from checkpoint 01"
	@echo "  make todo STAGE=NN      load the TODO start for a code stage (03/04/05/08)"
	@echo "  make up STAGE=NN        start this stage's processes"
	@echo "                          (stage 02: add WORKERS=1 to demo the single-thread choke)"
	@echo "  make lab STAGE=NN       tmux dashboard for ANY stage (01-10): every process in its"
	@echo "                          own pane + a control pane to drive it by hand (write/read on"
	@echo "                          01-04; kill/spawn nodes on 05-10)"
	@echo "  make lab-down           tear down the tmux dashboard + its processes"
	@echo "  make down               stop all workshop processes"
	@echo "  make incident STAGE=NN  run this stage's red->green check"
	@echo "  make checkpoint STAGE=NN restore kvstore/ to a known-good checkpoint"
	@echo "  make status             show the ladder of resolved incidents"

# The chmod after each seed matters on LINUX hosts: the container runs as root, so
# without it the copied files are root-owned on the bind mount and a host editor
# (e.g. VS Code) can't save into kvstore/. No-op effect on macOS/Windows.
verify:
	@bash tools/verify_setup.sh

start:
	rm -rf kvstore && cp -r checkpoints/01-* kvstore && chmod -R a+rw kvstore
	@echo "kvstore/ seeded from checkpoint 01"

todo:
	rm -rf kvstore && cp -r stages/$(STAGE)-* kvstore && chmod -R a+rw kvstore
	@echo "kvstore/ loaded with the TODO starting point for stage $(STAGE)"

up:
	WORKERS=$(WORKERS) bash tools/up.sh $(STAGE)

lab:
	WORKERS=$(WORKERS) bash tools/tmux_lab.sh $(STAGE)

lab-down:
	bash tools/tmux_lab.sh down

down:
	bash tools/down.sh

incident:
	@f=$$(ls incidents/incident_$(STAGE)_*.py 2>/dev/null | head -1); \
	if [ -z "$$f" ]; then \
	  echo "Stage $(STAGE) is a demo — no incident. Run 'make lab STAGE=$(STAGE)'."; \
	else \
	  python "$$f"; \
	fi

checkpoint:
	rm -rf kvstore && cp -r $(CP) kvstore && chmod -R a+rw kvstore
	@echo "kvstore/ restored to $(CP)"

status:
	python tools/status.py

# --- author-only ---
validate:
	bash tools/validate_ladder.sh

snapshot:
	cp -r kvstore checkpoints/$(STAGE)-snapshot
