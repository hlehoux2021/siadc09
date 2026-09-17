#!/bin/bash
# PreToolUse hook for Bash — auto-approve read-only pipelines and `&&` chains.
#
# Claude Code does not apply prefix rules (Bash(python3:*), Bash(tail:*), …) to a command
# that contains a pipe, a chain or a redirection, so `python3 -m pytest … 2>&1 | tail -15`
# and `git add … && git commit -F …` both prompt even though every part is allow-listed.
# This hook re-applies the project allow-list to each part and approves only when every one
# matches — it grants no authority that .claude/settings.json does not already grant for the
# single-command form. Heredocs and stdin redirections are never approved: their body is not
# a command, so there is nothing to check it against.
#
# Anything else exits silently (code 0, no output) and follows the normal prompt path.

set -u

cmd=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[ -n "$cmd" ] || exit 0

# Drop the harmless redirections first: `2>&1` must go before the `&` test below.
norm=$cmd
norm=${norm//2>&1/}
norm=${norm//&>\/dev\/null/}
norm=${norm//2>\/dev\/null/}
norm=${norm//>\/dev\/null/}

# `a && b` gets the same treatment as `a | b` — both are ignored by the prefix rules, and
# both are safe to approve only when every part is allowed on its own. Rewriting `&&` to `|`
# lets one split handle the two. `||` becomes an empty segment and falls through to the
# prompt (see below), which is the conservative outcome.
norm=${norm//&&/|}

# Plain commands are already handled by the permission rules — chains are our job.
case "$norm" in
	*'|'*) ;;
	*) exit 0 ;;
esac

# Refuse anything that can write, background, chain or substitute. A leftover `&` at this
# point is a background job or an unrecognized redirection, never a chain.
case "$norm" in
	*'>'* | *'<'* | *';'* | *'&'* | *'$('* | *'`'*) exit 0 ;;
esac

# `xargs [options] cmd …` is allowed only when `cmd …` is itself an allowed segment, so
# `grep -l … | xargs rm` still prompts.
unwrap_xargs() {
	# shellcheck disable=SC2086 # deliberate word splitting on the option list
	set -- $1
	shift # drop `xargs`
	while [ $# -gt 0 ]; do
		case "$1" in
		-[nIPLdsaE]) shift 2 || return 1 ;;
		-*) shift ;;
		*) break ;;
		esac
	done
	[ $# -gt 0 ] || return 1
	printf '%s' "$*"
}

# Mirrors permissions.allow in .claude/settings.json.
allowed_segment() {
	case "$1" in
	*' -exec '* | *' -delete'* | *' -ok '*) return 1 ;;
	xargs\ *)
		inner=$(unwrap_xargs "$1") || return 1
		allowed_segment "$inner"
		return $?
		;;
	python3 | python3\ *) return 0 ;;
	php\ *) return 0 ;;
	# `node --check file.js` is a syntax check — it never runs the script. Bare `node …` does.
	node\ --check\ *) return 0 ;;
	echo | echo\ *) return 0 ;;
	git\ * | gh\ *) return 0 ;;
	find\ *) return 0 ;;
	sed\ -n\ *) return 0 ;;
	cat\ * | grep\ * | jq\ * | cut\ *) return 0 ;;
	ls | ls\ * | wc | wc\ * | head | head\ * | tail | tail\ * | sort | sort\ * | uniq | uniq\ * | nl | nl\ *) return 0 ;;
	*) return 1 ;;
	esac
}

IFS='|' read -r -a segments <<<"$norm"
for seg in "${segments[@]}"; do
	seg="${seg#"${seg%%[![:space:]]*}"}" # ltrim
	seg="${seg%"${seg##*[![:space:]]}"}" # rtrim
	[ -n "$seg" ] || exit 0              # empty segment => `||` or a malformed pipeline
	allowed_segment "$seg" || exit 0
done

printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"Pipeline en lecture seule — chaque segment est déjà autorisé par .claude/settings.json"}}'
