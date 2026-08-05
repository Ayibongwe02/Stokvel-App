# App-scale onboarding — Part 1 of 2

## What "app-scale" means here
A single generic walkthrough treats a first-time **member** and a first-time
**admin** as the same person. They're not: an admin's first session needs to
end with "I know how to add my group," a member's needs to end with "I know
how to see my balance and pay in." Role-aware onboarding — branch the
content, not just the copy — is the standard pattern for multi-role apps
(Slack, Notion, Stripe all do this: the workspace *creator* gets extra
setup steps the *invitee* never sees).

## What this pass does
1. **Role-aware tour** (`templates/onboarding.html`)
   Everyone gets the same 4 core slides: Welcome → Groups & members → Live
   forecasts → Payments & menu. Admins additionally get two slides inserted
   before the close:
   - **Adding a member** — pre-register by role, or share the invite code.
   - **Your admin responsibilities** — invite/remove members, keep data
     accurate, manage the invite code, review Accuracy Health for the whole
     group (vs. a member who only sees their own numbers).

2. **Replayable, not just first-run** (`templates/settings.html`, `base.html`)
   A "Replay onboarding tour" button now lives in Settings → Help &
   onboarding. This was the most important UX gap in the original modal:
   it only ever fired once per browser via `localStorage`, so an admin who
   skipped it too fast, or a member promoted to admin later, had no way
   back in short of clearing site data.

3. **Role-change awareness**
   The dismissal flag is now keyed per role variant
   (`ledger_onboarding_v2_admin` / `ledger_onboarding_v2_member`), not one
   global flag. A member who gets promoted to admin will automatically see
   the admin slides once, instead of staying permanently dismissed from the
   member-level tour they already completed.

## Why this is "half" — what's deliberately left for part 2
Scoped down so this ships reviewable in one sitting, rather than as one
large, hard-to-check change. The modal-tour layer is done; the next layer
is putting guidance *at the point of use*, which is a separate, larger
piece of design + build work:

- **Contextual coach-marks on real UI**, not just modal slides — e.g. a
  one-time highlight pointing at the "Pre-register a member" form in
  Settings the first time an admin lands there, and at the invite-code
  field itself.
- **An onboarding checklist widget** on the Overview page for new admins
  ("Invite your first member," "Upload your first transaction," "Set up
  your invite code") with progress state stored server-side (per group),
  not just localStorage — so it's consistent across devices and dismissible
  per step, not all-or-nothing.
- **Role-aware empty states** — `templates/empty.html` currently reads the
  same for everyone; a first-time admin looking at an empty ledger should
  be pointed at "add a member" / "upload data," a member at "ask your
  admin to add you."
- **Event tracking** for tour completion/drop-off per slide, so this can
  actually be measured and iterated on rather than shipped and forgotten.
- **A short regional/copy pass** — the tour copy is currently English-only
  and untested against `templates/regional.html`'s localisation setup.
- **Cross-role QA**: confirm the tour behaves correctly for a user who
  belongs to multiple groups with different roles in each (admin of one,
  member of another) — right now the variant is computed from whichever
  group is currently active, which is probably right but hasn't been
  walked through by a second reviewer.

## Continuation prompt (paste this back in when ready)
> Continue the stokvel app onboarding work. Part 1 (role-aware modal tour,
> replay button in Settings, per-role dismissal) is done — see
> `docs/ONBOARDING_NOTES.md`. Now build part 2: (1) a dismissible checklist
> widget on the Overview page for new admins, backed by a server-side
> per-group `OnboardingProgress`-style model rather than localStorage, (2)
> one contextual coach-mark pointing at the "Pre-register a member" panel
> in Settings the first time an admin visits it, and (3) role-aware copy in
> `templates/empty.html` for the empty-ledger state. Keep the same visual
> language as the existing `.onboarding-*` CSS in `static/css/style.css`.
