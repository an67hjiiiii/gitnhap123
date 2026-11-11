Source persistence and chunk creation use transaction boundaries so a
multi-step write does not expose an incomplete authoritative record.
