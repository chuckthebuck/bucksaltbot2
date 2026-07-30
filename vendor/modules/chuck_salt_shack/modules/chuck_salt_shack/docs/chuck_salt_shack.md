# Chuck the Salt Shack

Chuck the Salt Shack, shown as **Salt Shack** in the module UI, contains the
Saltlick scripts compiled into this Chuckbot image.
Each Saltlick owns its typed inputs, structured outputs, permitted framework
actions, defaults, and run history.

## Running a Saltlick

1. Select an installed Saltlick.
2. Complete the generated Codex form.
3. Optionally add raw Pywikibot arguments under **Advanced**.
4. Run a dry preview.
5. Review the structured outputs and every planned action.
6. Apply the exact previewed plan when the Saltlick declares actions and you
   have the required right.

Apply runs must reproduce the preview's action-plan digest. If the plan changes,
Salt Shack rejects it and requires a new preview.

## Framework action catalog and batching

Saltlicks declare the action types they need in `actions.allowed`. The
framework executes the reviewed Pywikibot page catalog—`purge`, `edit`,
`delete`, `undelete`, `move`, `protect`, `touch`, `watch`, `unwatch`, and
`rollback`—under
either the `mediawiki.page.*` or `pywikibot.page.*` action namespace. Live
plans are processed in bounded batches, reusing a logged-in site per wiki and
recording best-effort batch progress in the module's Redis namespace. A
Saltlick cannot invoke an arbitrary Python method through this interface.

## Per-Saltlick access and emergency stops

Every discovered Saltlick automatically exposes three module-right suffixes:
`saltlick_<id>_preview`, `saltlick_<id>_apply`, and
`saltlick_<id>_estop`. Grant them through the normal framework module-grant
mechanism (for example, `module:chuck_salt_shack:saltlick_page_purger_preview`)
to authorize only that Saltlick. Existing Shack-wide `run_jobs`,
`apply_changes`, `estop`, and `manage` rights continue to work as broader
operator grants.

Stopping a Saltlick persists its disabled state in framework module config and
cancels only that Saltlick's active runs. The normal Shack module emergency
stop remains separate and disables/cancels the whole module.

## Adding a Saltlick

Saltlicks cannot be added from the browser. They are immutable image contents.

Duplicate a subdirectory under `modules/chuck_salt_shack/saltlicks/`, rename it, replace
the script, update its optional `saltlick.yaml`, and rebuild the module. The
Salt Shack registry and nested UI are generated from the discovered
directories.

## Page inputs

Page inputs contain a numeric namespace and title. Salt Shack loads the chosen
wiki's namespace catalog, then uses namespace-scoped Codex lookups for page
titles. A Saltlick may fix the namespace, allow a specific set, or expose the
selector. Multiple-page inputs use a searchable multi-select with removable
chips.

When the contract has one wiki input, page and namespace inputs follow it
automatically. Contracts with multiple wiki inputs use `wiki_input` to name the
one a page or namespace field should follow.

## Framework actions

Saltlick scripts describe actions; Chuckbot's framework executes them. Preview
runs never execute actions. The installed framework currently supports
`mediawiki.page.purge`; other action types must be added to the framework
catalog before a Saltlick may apply them.
