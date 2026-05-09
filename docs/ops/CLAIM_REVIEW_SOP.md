# Creator Profile Claim Review — Operator SOP

**Applies to:** C2.1 operator console at `/admin/creator-claims`
**Updated:** 2026-05-09
**Contact:** support@fragranceindex.ai

---

## Overview

Creators can claim their FragranceIndex.ai profile page via two methods:

| Method | How it works |
|--------|-------------|
| `bio_code` | Creator adds a unique `FTI-XXXXXXXX` code to their public bio/description. You confirm it is publicly visible. |
| `manual_review` | Creator submits a public URL as evidence of their association with the account. You assess the evidence. |

All claims default to `pending`. No claim is automatically approved.

---

## Target turnaround

| Volume | Target |
|--------|--------|
| Normal | Within 3 business days |
| High volume | Within 5 business days |

Reply to the creator at support@fragranceindex.ai if there is a delay.

---

## Step 1 — Open the console

Navigate to `/admin/creator-claims` while logged in with your admin account.

Default filter: **Pending**. Switch to Verified or Rejected to review historical claims.

---

## Step 2 — Review each pending claim

For each claim, check:

1. **Creator profile link** — open the creator's FTI profile page. Confirm this is a real, tracked creator with content.
2. **Evidence URL** — open the evidence URL in a new tab. Confirm it is publicly accessible without logging in.
3. **Method-specific check** (see below).
4. **Reviewer note** — read if provided; it may explain where to find the code or evidence.

---

## Step 3 — Method-specific verification

### bio_code

1. Open the evidence URL (the creator's public profile page).
2. Look for the `FTI-XXXXXXXX` code anywhere in the visible page text — bio, description, About tab, pinned comment.
3. The code must match the format exactly (FTI- prefix, 8 uppercase alphanumeric characters).
4. The code does **not** need to be the only content — it just needs to be present and publicly readable.
5. **Approve** if code is visible. **Reject** if code is absent or the URL is inaccessible.

> You do not need to verify the code against a hash. Presence of the correct format code at the claimed URL is sufficient.

### manual_review

Assess whether the evidence URL reasonably demonstrates that this person controls or is associated with the claimed creator account. Acceptable evidence includes:

| Evidence type | Acceptable |
|--------------|-----------|
| Personal/business website with a link to the channel/profile | ✓ Yes |
| Pinned post or video from the creator referencing their identity | ✓ Yes |
| Public announcement ("This is my channel" style post) | ✓ Yes |
| A screenshot (not a URL) | ✗ No — must be a URL |
| A URL that requires login to view | ✗ No — must be publicly accessible |
| A URL that does not load or returns 404 | ✗ No |
| A URL that belongs to a different creator | ✗ No |
| A generic social sharing link with no visible connection | ✗ Use judgment — reject if unclear |

If the evidence is borderline, lean toward rejection with a clear, constructive reason. The creator can resubmit.

---

## Step 4 — Approve or Reject

### Approve

Click **Approve** in the console.

Sets: `claim_status = 'verified'`, `verified_at = NOW()`, `reviewed_by = your email`.

The creator's profile page will now show the **Verified Creator** badge. No email is sent automatically — the creator will see the badge next time they visit their profile page.

### Reject

Click **Reject** and enter a rejection reason. The reason is shown to the creator — write it clearly and constructively.

Sets: `claim_status = 'rejected'`, `rejection_reason = <your text>`, `reviewed_by = your email`.

The creator can resubmit a new claim. The rejected claim row is preserved for audit purposes.

---

## Rejection reason templates

Copy and adapt as needed:

**bio_code — code not found:**
> The verification code was not visible at the URL you provided. Make sure the code (FTI-XXXXXXXX) is added to your public profile description and the URL links directly to that page, then resubmit.

**bio_code — URL inaccessible:**
> The evidence URL returned an error or requires a login to view. Please provide a direct public link to your profile page and resubmit.

**manual_review — insufficient evidence:**
> The evidence URL does not clearly show a connection between you and this creator account. Please submit a public URL (your website, a pinned post, or a public announcement) that directly references this channel or profile.

**manual_review — URL not publicly accessible:**
> The evidence URL requires a login or is not publicly accessible. Please provide a URL that anyone can open without an account.

**Wrong creator claimed:**
> The evidence you provided appears to be associated with a different creator account. Please verify you are claiming the correct profile.

---

## SQL reference (direct DB access via Railway)

Use the PUBLIC database URL (gondola.proxy.rlwy.net:34404) from the Postgres service variables, or access via `/admin/creator-claims` in the UI.

```sql
-- View all pending claims
SELECT id, user_id, platform, creator_id, claim_method, evidence_url,
       reviewer_notes, claimed_at
FROM creator_profile_claims
WHERE claim_status = 'pending'
ORDER BY claimed_at ASC;

-- Approve
UPDATE creator_profile_claims
SET claim_status = 'verified',
    verified_at  = NOW(),
    reviewed_at  = NOW(),
    reviewed_by  = 'operator'
WHERE id = '<claim_uuid>'
  AND claim_status = 'pending';

-- Reject
UPDATE creator_profile_claims
SET claim_status     = 'rejected',
    reviewed_at      = NOW(),
    reviewed_by      = 'operator',
    rejection_reason = '<reason>'
WHERE id = '<claim_uuid>'
  AND claim_status = 'pending';

-- Revoke a previously approved claim (e.g. dispute or abuse)
UPDATE creator_profile_claims
SET claim_status = 'revoked',
    reviewed_at  = NOW(),
    reviewed_by  = 'operator'
WHERE id = '<claim_uuid>';
```

---

## Edge cases

**Creator claims a profile they do not own:**
Reject with reason "The evidence does not demonstrate control of this account." If abuse is suspected, note it in reviewer_notes and do not approve any future claims from this user_id for this creator.

**Two different users claim the same creator:**
The partial UNIQUE index allows only one `pending` or `verified` claim per `(user_id, platform, creator_id)`. Different users can each submit a claim for the same creator profile — approve only the one with credible evidence. If both look credible, hold the second and email support@fragranceindex.ai to escalate.

**Creator asks to remove their verified badge:**
Update claim_status to `revoked` via SQL. The badge will disappear from their profile page on next load.

**Creator changes their bio URL after verification:**
No action needed — the claim is already approved. The bio_code can be removed.

---

## What this system does NOT do

- No OAuth. No platform API access. No private account data.
- No automatic ingestion or pipeline changes triggered by approvals.
- No email sent to creators on approve/reject — they see status on their profile page.
- No creator_oauth_grants rows are created or modified.
