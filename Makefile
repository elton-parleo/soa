# Repo-level developer conveniences. Nothing here runs in CI/deploy
# automatically — see each target's own comment for when to run it.

.PHONY: keydirectory

# W3: (re)generates the Web Bot Auth key directory document from
# whatever BOT_SIGNING_KEY is currently set in the environment — run
# this on key rotation, then publish the output at
# https://bots.parleo.io/.well-known/http-message-signatures-directory
# (serving it is an ops step, not part of this repo). Never commits
# its output — see apps/pipeline/scripts/generate_key_directory.py's
# own docstring for why.
keydirectory:
	cd apps/pipeline && python3 scripts/generate_key_directory.py
