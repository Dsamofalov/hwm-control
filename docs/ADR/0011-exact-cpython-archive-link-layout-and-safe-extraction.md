# ADR 0011: Exact CPython archive link layout and containment-safe extraction

**Status:** Accepted  
**Date:** 2026-08-28  
**Task:** I10-0091 / Issue #91

## Context

The exact actions/python-versions CPython 3.12.10 runtime artifact remains authoritative. Its URL, size 121612690 bytes, and SHA-256 b9bd943c5fc9244f796deef42c59d29ab9278d8a718851c67de6b44846320f33 were verified before inert archive inspection. Runtime v1 rejected every archive link, while live #85 acceptance proved that the pinned artifact contains links. I10-0091 defines runtime v2 without changing the artifact, adding credentials, running Graphify, or weakening containment.

Owner authority in Issue #91 comment 5450830109 permits one exact "." archive-root sentinel and one leading "./" tar transport prefix while retaining raw-to-canonical identity and strict rejection of embedded dot segments, traversal, ambiguity, dangling links, cycles, special members, and root escape.

## Exact inert-header evidence

Evidence-v3 ran on exact task head 20c9a2f6e812b5e5cf158ab5e18f96f5e0ba9b96 in Infrastructure CI 33159987768, job 98811838917. The archive contains 9341 canonical records: one root sentinel, 447 directories, 8884 regular files, 9 symlinks, 0 hardlinks, and 0 special members. Canonical inventory bytes are 2361714 and SHA-256 is 266fbc38be6ffdc9c565953d44cc208e74d6db8a2f038186580fd4904279f3db.

The root sentinel is raw ".", tar type "5", mode 493, size 0, empty linkname, normalized_path null, extract=false. The exact 9 symlinks terminate at regular members. There are 0 hardlinks and 0 special members.

## Decision

Adopt hwm-graphify-acceptance-runtime/v2 as a forward-only successor to v1. All v1 artifact, acquisition, network, cache, credential, runtime-verification, and 900-second semantic builder timer requirements remain unchanged.

Runtime v2 binds acceptance to the exact canonical inventory and ordered 9 symlinks in the contract. Any change in raw name, normalized path, type, mode, size, linkname, resolved target, terminal target, counts, or inventory digest fails closed.

### raw-to-canonical normalization

Raw "." is the unique archive-root sentinel and creates no filesystem object. For ordinary members exactly one leading "./" is transport syntax and is removed only for filesystem namespace. One trailing slash is accepted only for a directory. Raw spellings remain canonical evidence. Empty, absolute, drive-prefixed, backslash, control, non-NFC, repeated-prefix, embedded "."/"..", duplicate-canonical, and escaping paths are rejected.

Symlink linknames resolve relative to the member parent. Hardlinks would resolve from archive root, but the exact inventory contains 0 hardlinks. Dangling targets, cycles, link-to-special, and target escape remain forbidden.

### two-pass containment-safe extraction

Pass 0 validates the complete inventory and exact links before output content exists. Pass 1 creates only directories and regular files, never follows links, and requires real-directory parents. Pass 2 creates only the exact allowlisted links and never overwrites. Post-extraction validation proves exact counts, link containment, absence of dangling links/cycles/unexpected objects, and no write outside task-local root. Cleanup is mandatory.

## Consequences

Runtime v1 blob remains immutable historical evidence. Runtime v2 is mandatory for resumed #85. Old #85 control/lab branches remain historical anchors; #85 must resume on fresh replacement branches after this merge. #73 remains paused until #85 completes. I10-0091 changes no hwm-lab source, .github path, product/context state, credential, runtime installation, or Graphify output.
