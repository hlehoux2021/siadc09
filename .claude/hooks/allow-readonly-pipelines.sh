#!/bin/bash
# PreToolUse hook for Bash — auto-approve read-only pipelines, `&&` chains, and `;` chains.
#
# Claude Code does not apply prefix rules (Bash(python3:*), Bash(tail:*), …) to a command
# that contains a pipe, a chain or a redirection, so `python3 -m pytest … 2>&1 | tail -15`,
# `git add … && git commit -F …`, and `find … ; find … | head -5` all prompt even though
# every part is allow-listed.
# This hook re-applies the project allow-list to each part and approves only when every one
# matches — it grants no authority that .claude/settings.json does not already grant for the
# single-command form. Heredocs and stdin redirections are never approved: their body is not
# a command, so there is nothing to check it against.
#
# Anything else exits silently (code 0, no output) and follows the normal prompt path.

set -u

cmd=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[ -n "$cmd" ] || exit 0

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
	curl\ *) return 0 ;;
	sed\ -n\ *) return 0 ;;
	cat\ * | grep\ * | jq\ * | cut\ * | awk\ *) return 0 ;;
	ls | ls\ * | wc | wc\ * | head | head\ * | tail | tail\ * | sort | sort\ * | uniq | uniq\ * | nl | nl\ *) return 0 ;;
	*) return 1 ;;
	esac
}

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

# Splits $1 on top-level `|`, `&&`, and `;` into the TOP_SEGS array, skipping delimiters
# that appear inside '...' or "..." quotes — a literal `|` in a grep pattern like "^a\|^b"
# must not be mistaken for a pipe. Returns 1 (unsafe / unparsable) on: an unterminated quote,
# `$(...)`/backtick command substitution anywhere except inside single quotes, `>`/`<`
# redirection, a lone `&` background job, or `||`.
split_top_level() {
	local s="$1" i=0 n c nextc insq=0 indq=0 cur=''
	TOP_SEGS=()
	n=${#s}
	while [ "$i" -lt "$n" ]; do
		c="${s:$i:1}"

		if [ "$insq" -eq 1 ]; then
			cur="$cur$c"
			[ "$c" = "'" ] && insq=0
			i=$((i + 1))
			continue
		fi

		if [ "$c" = '\' ]; then
			cur="$cur$c"
			i=$((i + 1))
			if [ "$i" -lt "$n" ]; then
				cur="$cur${s:$i:1}"
				i=$((i + 1))
			fi
			continue
		fi

		nextc="${s:$((i + 1)):1}"
		if [ "$c" = '$' ] && [ "$nextc" = '(' ]; then
			return 1
		fi
		if [ "$c" = '`' ]; then
			return 1
		fi

		if [ "$indq" -eq 1 ]; then
			cur="$cur$c"
			[ "$c" = '"' ] && indq=0
			i=$((i + 1))
			continue
		fi

		# Outside any quotes.
		if [ "$c" = "'" ]; then
			insq=1
			cur="$cur$c"
		elif [ "$c" = '"' ]; then
			indq=1
			cur="$cur$c"
		elif [ "$c" = '|' ]; then
			[ "$nextc" = '|' ] && return 1
			TOP_SEGS+=("$cur")
			cur=''
		elif [ "$c" = ';' ]; then
			TOP_SEGS+=("$cur")
			cur=''
		elif [ "$c" = '&' ]; then
			if [ "$nextc" = '&' ]; then
				TOP_SEGS+=("$cur")
				cur=''
				i=$((i + 2))
				continue
			else
				return 1
			fi
		elif [ "$c" = '>' ] || [ "$c" = '<' ]; then
			return 1
		else
			cur="$cur$c"
		fi
		i=$((i + 1))
	done

	[ "$insq" -eq 0 ] && [ "$indq" -eq 0 ] || return 1
	TOP_SEGS+=("$cur")
	return 0
}

# Drops the harmless redirections `split_top_level` would otherwise choke on: `2>&1` and
# `>/dev/null` variants contain a bare `>` that its redirection check rejects, even though
# they carry no risk (stderr merge, discarding output).
strip_redirects() {
	local s="$1"
	s=${s//2>&1/}
	s=${s//&>\/dev\/null/}
	s=${s//2>\/dev\/null/}
	s=${s//>\/dev\/null/}
	printf '%s' "$s"
}

# `for VAR in LIST; do BODY; done` — batch read-only inspection across a fixed file
# list (e.g. `for f in a.md b.md; do grep ... "$f" | head -5; done`). Approve only when
# every LIST item is a literal token (no globs/substitution) and every statement in
# BODY is itself an allowed segment.
try_allow_for_loop() {
	[[ $cmd =~ ^for\ [A-Za-z_][A-Za-z0-9_]*\ in\ ([^\;]+)\;[[:space:]]*do[[:space:]](.*)\;[[:space:]]*done$ ]] || return 1
	list=${BASH_REMATCH[1]}
	body=$(strip_redirects "${BASH_REMATCH[2]}")

	for item in $list; do
		case "$item" in
		*[\$\`\*\?\[\]\(\)\<\>\&\;\|\'\"]*) return 1 ;;
		esac
	done

	split_top_level "$body" || return 1
	for seg in "${TOP_SEGS[@]}"; do
		seg="${seg#"${seg%%[![:space:]]*}"}"
		seg="${seg%"${seg##*[![:space:]]}"}"
		[ -n "$seg" ] || return 1
		allowed_segment "$seg" || return 1
	done

	printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"Boucle for en lecture seule — chaque item de la liste et chaque segment du corps sont déjà autorisés par .claude/settings.json"}}'
	return 0
}

try_allow_for_loop && exit 0

# Drop the harmless redirections first: `2>&1` must go before the `&` test below.
norm=$(strip_redirects "$cmd")

split_top_level "$norm" || exit 0

# Plain commands are already handled by the permission rules — chains are our job.
[ "${#TOP_SEGS[@]}" -gt 1 ] || exit 0

for seg in "${TOP_SEGS[@]}"; do
	seg="${seg#"${seg%%[![:space:]]*}"}" # ltrim
	seg="${seg%"${seg##*[![:space:]]}"}" # rtrim
	[ -n "$seg" ] || exit 0              # empty segment => malformed pipeline
	allowed_segment "$seg" || exit 0
done

printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"Pipeline en lecture seule — chaque segment est déjà autorisé par .claude/settings.json"}}'
