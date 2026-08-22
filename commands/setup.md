---
description: Check what Sporhund can do right now, and set up the vehicle-registry key if it is missing.
---

Run Sporhund's `check_setup` tool and report the result to me in plain language:
which tools are live, and whether the Statens vegvesen vehicle-registry key is
configured.

If a key is configured, verify it with `check_setup(verify_key=true)` and tell me
whether Statens vegvesen accepted it.

If it is missing or rejected, follow the `vegvesen-key` skill to walk me through
ordering and installing my own key. Never ask me to paste the key into this chat.

Also tell me whether the optional Facebook Marketplace source is installed. If it
isn't, mention it exists and what it costs to switch on, but don't install
anything — follow the `facebook-source` skill only if I ask for it.
