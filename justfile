#!/usr/bin/env -S just --justfile

set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

talos_dir := justfile_dir() + '/talos'

mod bootstrap "bootstrap"
mod kube "kubernetes"
mod talos "talos"

[private]
default:
    just -l

[private]
log lvl msg *args:
    gum log -t rfc3339 -s -l "{{ lvl }}" "{{ msg }}" {{ args }}

machine-controller node:
    just template "{{ talos_dir }}/nodes/{{ node }}.yaml.j2" | yq -e 'select(.machine) | (.machine.type == "controlplane") // ""'

# [private]
template file *args:
    eval "$(vault kv get -format=json -mount=secrets kubernetes | jq -r '.data.data | to_entries[] | "export \(.key)=\(.value|@sh)"')" && \
        minijinja-cli "{{ file }}" {{ args }}
# gomplate -d vault=vault:///kv2 --file "{{ file }}" {{ args }}

vault2env:
    just log info "Loading secrets from Vault..."

    just log info "Secrets loaded."
