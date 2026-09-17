#!/bin/bash
# PreToolUse hook for Bash — auto-approve read-only pipelines.
#
# Claude Code does not apply prefix rules (Bash(python3:*), Bash(tail:*), …) to a command
# that contains a pipe or a redirection, so `python3 -m pytest … 2>&1 | tail -15` prompts
# even though both halves are allow-listed. This hook re-applies the project allow-list to
# each segment of the pipeline and approves only when every segment matches — it grants no
# authority that .claude/settings.json does not already grant for the unpiped form.
#
# Anything else exits silently (code 0, no output) and follows the normal prompt path.

set -u

cmd=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[ -n "$cmd" ] || exit 0

# Plain commands are already handled by the permission rules — only pipelines are our job.
case "$cmd" in
	*'|'*) ;;
	*) exit 0 ;;
esac

# Drop the harmless redirections, then refuse anything that can write, chain or substitute.
norm=$cmd
norm=${norm//2>&1/}
norm=${norm//&>\/dev\/null/}
norm=${norm//2>\/dev\/null/}
norm=${norm//>\/dev\/null/}
case "$norm" in
	*'>'* | *';'* | *'&'* | *'$('* | *'`'*) exit 0 ;;
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
