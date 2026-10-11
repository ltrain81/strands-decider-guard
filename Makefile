# Entry points for the common paths. `make` (or `make help`) lists them.
# Variables: REGION, PROFILE, ADMIN_EMAIL, AGENTS (default claude,codex; add kiro to opt in), LANGUAGE (en|ko), DEPLOY_ARGS, INSTALL_ARGS

REGION       ?=
PROFILE      ?=
ADMIN_EMAIL  ?=
AGENTS       ?= claude,codex
LANGUAGE     ?=
DEPLOY_ARGS  ?=
INSTALL_ARGS ?=

aws_args     = $(if $(REGION),--region $(REGION)) $(if $(PROFILE),--profile $(PROFILE))
install_args = --agents $(AGENTS) $(if $(LANGUAGE),--language $(LANGUAGE)) $(INSTALL_ARGS)

.DEFAULT_GOAL := help
.PHONY: help doctor local local-console local-stop preflight deploy install status health stop start console \
        add-admin uninstall demo test test-model eval destroy

help: ## list targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

doctor: ## check this machine and print the recommended path (read-only)
	@scripts/doctor.sh $(aws_args)

# ---------- local, no AWS ----------
local: ## run strands-decider here + install the hooks in local mode
	@scripts/local-decider.sh start
	@client/install.sh --local $(install_args)
	@echo; echo "Next: make local-console (policy UI)  |  make demo  |  make uninstall to remove the hooks"

local-console: ## open the policy console against the local setup (no login)
	@python3 admin/dev_server.py

local-stop: ## stop the local strands-decider server
	@scripts/local-decider.sh stop

# ---------- AWS ----------
preflight: ## check AWS credentials, GPU quota and IAM headroom without deploying
	@./deploy.sh $(aws_args) --preflight-only

deploy: ## deploy to AWS (REGION=..., ADMIN_EMAIL=... recommended)
	@./deploy.sh $(aws_args) $(if $(ADMIN_EMAIL),--admin-email $(ADMIN_EMAIL)) $(DEPLOY_ARGS)

install: ## install the hooks against the AWS deployment (reads outputs.json)
	@client/install.sh --outputs outputs.json $(if $(PROFILE),--profile $(PROFILE)) $(install_args)

status: ## deployment status
	@./ctl.sh status
health: ## guard -> decider health
	@./ctl.sh health
stop: ## stop the GPU host (saves cost)
	@./ctl.sh stop
start: ## start the GPU host again
	@./ctl.sh start
console: ## print the policy console URL
	@./ctl.sh console
add-admin: ## create a console login: make add-admin ADMIN_EMAIL=you@example.com
	@./ctl.sh add-admin $(ADMIN_EMAIL)

destroy: ## delete the AWS deployment (asks for confirmation)
	@./destroy.sh $(aws_args)

# ---------- both ----------
uninstall: ## remove the hooks from this machine's agent configs
	@client/install.sh --uninstall --agents claude,kiro,codex

demo: ## run the scripted demo (DEMO_LANG=en|ko)
	@demo/run_demo.sh

test: ## offline tests (no model, no AWS) + script syntax
	@python3 -I tests/test_offline.py
	@for f in *.sh scripts/*.sh client/*.sh demo/*.sh; do bash -n "$$f" || exit 1; done; echo "shell syntax ok"

test-model: ## policy feature tests against a running decider (make local first)
	@python3 -I tests/test_with_model.py

eval: ## accuracy on the synthetic samples (needs a running decider)
	@python3 -I tests/eval_accuracy.py && python3 -I tests/eval_accuracy.py --holdout
