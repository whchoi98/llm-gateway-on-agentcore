#!/bin/bash
# Tests for the secret patterns in .claude/hooks/secret-scan.sh
# Validates true positives (must detect) and false positives (must not detect).
#
# The hook's PATTERNS array is the single source: it is read from the hook and matched with
# python3 `re`, the engine the hook uses, so a pattern that works only under grep -P fails here.
#
# Note: Some test tokens are constructed at runtime via string concatenation
# to avoid triggering GitHub Push Protection on this test file.

FIXTURES="tests/fixtures"
SP_HOOK=".claude/hooks/secret-scan.sh"

# A child bash evaluates only the array definition, so quoting and comments parse exactly as in the hook.
SP_PATTERNS=()
while IFS= read -r sp_line; do
    SP_PATTERNS+=("$sp_line")
done < <(bash -c "$(sed -n '/^PATTERNS=(/,/^)/p' "$SP_HOOK")"'
printf "%s\n" "${PATTERNS[@]}"' 2>/dev/null || true)

if [ "${#SP_PATTERNS[@]}" -gt 0 ]; then
    pass "PATTERNS read from $SP_HOOK (${#SP_PATTERNS[@]} patterns)"
else
    fail "PATTERNS read from $SP_HOOK" "no PATTERNS=( ... ) array found"
    SP_PATTERNS=('a^')   # never matches; keeps the checks below running under set -u
fi

SP_BAD=$(python3 -c '
import re, sys
for pattern in sys.argv[1:]:
    try:
        re.compile(pattern)
    except re.error as err:
        print("%s (%s)" % (pattern, err))
' "${SP_PATTERNS[@]}" 2>&1 || true)
assert_eq "Every PATTERNS entry compiles with python3 re" "" "$SP_BAD"

# sp_match <text>: print the first hook pattern that matches <text>, or nothing
sp_match() {
    printf '%s' "$1" | python3 -c '
import re, sys
text = sys.stdin.read()
for pattern in sys.argv[1:]:
    try:
        if re.search(pattern, text):
            print(pattern)
            break
    except re.error:
        pass
' "${SP_PATTERNS[@]}" 2>/dev/null || true
}
SP_TP_SAMPLES=()
sp_detects() {
    local hit
    SP_TP_SAMPLES+=("$2")
    hit=$(sp_match "$2")
    if [ -n "$hit" ]; then pass "$1"; else fail "$1" "no secret-scan.sh pattern matched"; fi
}
sp_ignores() {
    local hit
    hit=$(sp_match "$2")
    if [ -z "$hit" ]; then pass "$1"; else fail "$1" "matched pattern '$hit' (expected no match)"; fi
}

# --- True Positive Tests ---

sp_detects "TP: AWS Access Key ID" "AKIAIOSFODNN7EXAMPLE"
sp_detects "TP: GitHub PAT" "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
sp_detects "TP: GitHub OAuth Token" "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
sp_detects "TP: Azure Connection String" "DefaultEndpointsProtocol=https;AccountName=myaccount"
sp_detects "TP: Password assignment" 'password = "mysecretpassword123"'
sp_detects "TP: API key assignment" 'api_key = "sk_abcdefghijklmnop"'

# Runtime-constructed tokens (avoid GitHub Push Protection)
# Google API Key
GAPI_PREFIX="AIza"
GAPI_BODY="SyABCDEFGHIJKLMNOPQRSTUVWXYZ1234567"
sp_detects "TP: Google API Key" "${GAPI_PREFIX}${GAPI_BODY}"

# Slack Bot / User Token
SLACK_PREFIX="xoxb-"
SLACK_USER_PREFIX="xoxp-"
SLACK_BODY="123456789012-1234567890123-abcdef"
sp_detects "TP: Slack Bot Token" "${SLACK_PREFIX}${SLACK_BODY}"
sp_detects "TP: Slack User Token" "${SLACK_USER_PREFIX}${SLACK_BODY}"

# Stripe Secret / Restricted Key
STRIPE_PREFIX="sk_live_"
STRIPE_RK_PREFIX="rk_live_"
STRIPE_BODY="ABCDEFGHIJKLMNOPQRSTUVWX"
sp_detects "TP: Stripe Secret Key" "${STRIPE_PREFIX}${STRIPE_BODY}"
sp_detects "TP: Stripe Restricted Key" "${STRIPE_RK_PREFIX}${STRIPE_BODY}"

# AWS Secret Access Key (AWS documentation example value) in ini, .env, and JSON form
SP_AWS_NAME="aws_secret_access""_key"
SP_AWS_SECRET="wJalrXUtnFEMI/K7MDENG/""bPxRfiCYEXAMPLEKEY"
sp_detects "TP: AWS Secret Key (ini)" "${SP_AWS_NAME} = ${SP_AWS_SECRET}"
sp_detects "TP: AWS Secret Key (.env, upper case)" "$(printf '%s' "$SP_AWS_NAME" | tr 'a-z' 'A-Z')=${SP_AWS_SECRET}"
sp_detects "TP: AWS Secret Key (JSON)" "\"${SP_AWS_NAME}\": \"${SP_AWS_SECRET}\""

# OpenAI, GitHub fine-grained PAT, Google OAuth, generic secret assignment
SP_ALNUM20="ABCDEFGHIJKLMNOPQRST"
sp_detects "TP: OpenAI API Key" "sk-${SP_ALNUM20}T3Blbk""FJ${SP_ALNUM20}"
sp_detects "TP: GitHub Fine-grained PAT" "github_pat_$(printf 'A%.0s' {1..82})"
sp_detects "TP: Google OAuth Token" "ya29.$(printf 'b%.0s' {1..50})"
sp_detects "TP: Secret assignment" "secret = \"hunter2""hunter2\""

# Anthropic and current OpenAI keys have base64url bodies, so `_` and `-` appear anywhere
SP_B64URL=$(printf 'aB3_x-Y9%.0s' {1..12})
sp_detects "TP: Anthropic API Key (base64url body)" "sk-ant-""api03-${SP_B64URL}AA"
sp_detects "TP: OpenAI project key" "sk-""proj-${SP_B64URL}"
sp_detects "TP: OpenAI service account key" "sk-""svcacct-${SP_B64URL}"
sp_detects "TP: OpenAI admin key" "sk-""admin-${SP_B64URL}"

# Private keys (PEM, OpenSSH, and PGP headers)
SP_PEM_BEGIN="-----BEGIN"
SP_PEM_KEY="PRIVATE ""KEY-----"
sp_detects "TP: PKCS#8 private key" "${SP_PEM_BEGIN} ${SP_PEM_KEY}"
sp_detects "TP: RSA private key" "${SP_PEM_BEGIN} RSA ${SP_PEM_KEY}"
sp_detects "TP: OpenSSH private key" "${SP_PEM_BEGIN} OPENSSH ${SP_PEM_KEY}"
sp_detects "TP: EC private key" "${SP_PEM_BEGIN} EC ${SP_PEM_KEY}"
sp_detects "TP: PGP private key block" "${SP_PEM_BEGIN} PGP PRIVATE ""KEY BLOCK-----"

# Quoted password, secret, and API key assignments in any case, in JSON, and in longer names
SP_PW="hunter2""hunter2"
sp_detects "TP: Password in JSON" "{\"password\": \"${SP_PW}\"}"
sp_detects "TP: Password, upper-case name" "PASSWORD=\"${SP_PW}\""
sp_detects "TP: Password, prefixed name" "DB_PASSWORD: '${SP_PW}'"
sp_detects "TP: Password with spaces" 'password = "correct horse battery"'
sp_detects "TP: Django SECRET_KEY" "SECRET_KEY = 'django-insecure-9f8a7s6d5f4g'"
sp_detects "TP: camelCase clientSecret" "clientSecret: \"${SP_PW}\""
sp_detects "TP: API key in JSON" '"api_key": "abcdefghijklmnop"'
sp_detects "TP: camelCase apiKey" "apiKey: 'abcdefghijklmnop'"

# Every hook pattern must be exercised by at least one sample above, so a new pattern needs a TP.
SP_UNTESTED=$(python3 -c '
import re, sys
patterns, samples = sys.argv[1].split("\n"), sys.argv[2].split("\n")
for pattern in patterns:
    try:
        rule = re.compile(pattern)
    except re.error:
        continue
    if not any(rule.search(sample) for sample in samples):
        print(pattern)
' "$(printf '%s\n' "${SP_PATTERNS[@]}")" "$(printf '%s\n' "${SP_TP_SAMPLES[@]}")" 2>&1 || true)
assert_eq "Every PATTERNS entry has a true-positive sample" "" "$SP_UNTESTED"

# --- False Positive Tests ---

sp_ignores "FP: Normal base64 not a secret" "dGhpcyBpcyBhIHRlc3QgYmFzZTY0IHN0cmluZw=="
sp_ignores "FP: SHA256 hash not a secret" "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
sp_ignores "FP: Git commit hash not a token" "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
sp_ignores "FP: URL path not a secret" "https://api.example.com/v1/users/profile"
sp_ignores "FP: Empty password not detected" 'password = ""'
sp_ignores "FP: Short API key not detected" 'api_key = "short"'
sp_ignores "FP: Version string not a secret" "VERSION=1.0.0-alpha.1+build.123"
sp_ignores "FP: PEM header not a secret" "-----BEGIN CERTIFICATE-----"
sp_ignores "FP: AWS secret read from the environment" "${SP_AWS_NAME} = \${AWS_SECRET_ACCESS_KEY}"
sp_ignores "FP: 40-char base64 without a key name" "value = ${SP_AWS_SECRET}"
sp_ignores "FP: PEM public key header" "${SP_PEM_BEGIN} PUBLIC KEY-----"
sp_ignores "FP: PGP public key block" "${SP_PEM_BEGIN} PGP PUBLIC KEY BLOCK-----"
sp_ignores "FP: Short OpenAI-style prefix" "sk-proj-short"
# A value that starts with $ % { < is a reference or placeholder, not a literal
sp_ignores "FP: Password from an environment variable" 'password: "${DB_PASSWORD}"'
sp_ignores "FP: Helm template value" 'secret: "{{ .Values.secret }}"'
sp_ignores "FP: Python %-format placeholder" 'password = "%(db_password)s"'
sp_ignores "FP: Angle-bracket placeholder" 'api_key = "<your-api-key-here>"'
sp_ignores "FP: Password read from os.environ" 'password = os.environ["DB_PASSWORD"]'
sp_ignores "FP: Name that only starts with SECRET" 'SECRET_NAME = "my-app-secret-name"'

# --- Bulk scan: fixture files (non-comment, non-blank lines) ---

# sp_count_lines <file>: print "<lines matching any hook pattern> <lines>"
sp_count_lines() {
    python3 -c '
import re, sys
rules = []
for pattern in sys.argv[2:]:
    try:
        rules.append(re.compile(pattern))
    except re.error:
        pass
with open(sys.argv[1], encoding="utf-8") as handle:
    lines = [line for line in handle.read().splitlines() if line.strip() and not line.startswith("#")]
print(sum(1 for line in lines if any(rule.search(line) for rule in rules)), len(lines))
' "$1" "${SP_PATTERNS[@]}" 2>/dev/null || echo "0 0"
}

TP_FILE="$FIXTURES/secret-samples.txt"
if [ -f "$TP_FILE" ]; then
    read -r TP_DETECTED TP_TOTAL <<< "$(sp_count_lines "$TP_FILE")"
    if [ "$TP_DETECTED" -ge 6 ]; then
        pass "Bulk TP: detected $TP_DETECTED/$TP_TOTAL secrets in fixture file (threshold: >=6)"
    else
        fail "Bulk TP: detected $TP_DETECTED/$TP_TOTAL secrets in fixture file" "expected at least 6"
    fi
else
    skip "Bulk TP test" "fixtures file not found"
fi

FP_FILE="$FIXTURES/false-positives.txt"
if [ -f "$FP_FILE" ]; then
    read -r FP_DETECTED FP_TOTAL <<< "$(sp_count_lines "$FP_FILE")"
    if [ "$FP_DETECTED" -le 1 ]; then
        pass "Bulk FP: $FP_DETECTED/$FP_TOTAL false positives (threshold: <=1)"
    else
        fail "Bulk FP: $FP_DETECTED/$FP_TOTAL false positives" "expected at most 1"
    fi
else
    skip "Bulk FP test" "fixtures file not found"
fi
