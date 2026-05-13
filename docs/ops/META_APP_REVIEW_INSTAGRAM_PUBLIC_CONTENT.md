# Meta App Review — Instagram Public Content Access
# Submission Support Document

**Phase:** IG1-R  
**Status:** IN PREPARATION — Business Verification in review  
**Updated:** 2026-05-13  
**Demo route:** `/admin/meta-review/instagram` (admin-only)  

This document is founder support material only. Do not submit automatically.
All answers should be reviewed and edited by the founder before submission.

---

## 1. Permissions / Features Being Submitted

| Permission / Feature | Required | Purpose |
|---------------------|----------|---------|
| **Instagram Public Content Access** | Yes — primary | Enables Hashtag Search API for trend monitoring |
| `instagram_basic` | Yes | Required baseline for Instagram Graph API access |
| `pages_read_engagement` | Yes | Read engagement data from connected Facebook Page |
| `pages_show_list` | Yes | Required to confirm connected Page identity |
| `public_profile` | Yes | Basic app identity confirmation |

**Intentionally NOT submitted:**
- `instagram_content_publish` — we do not post on behalf of any account
- `business_management` — no business management operations needed

---

## 2. Why Each Permission Is Requested

### Instagram Public Content Access
This is the core IG1 feature. It enables the `ig_hashtag_search` endpoint and the `/{hashtag-id}/recent_media` and `/{hashtag-id}/top_media` endpoints.

FragranceIndex.ai uses these endpoints to monitor public fragrance conversation on Instagram by querying public posts associated with fragrance hashtags (e.g., `#perfume`, `#fragrance`, `#nicheperfume`). This is the only compliant, scalable path for hashtag-level public trend monitoring.

Without this feature, IG1 cannot proceed.

### `instagram_basic`
Required baseline for all Instagram Graph API operations. Allows the app to read basic account information from the connected Instagram Business Account and is prerequisite for Hashtag Search.

### `pages_read_engagement`
Required to read the connected Facebook Page's engagement data. This establishes the Page → Instagram Business Account relationship that enables the `user_id` parameter in hashtag search calls.

### `pages_show_list`
Required to enumerate the Facebook Pages connected to the app user. Used to confirm that the correct Page (fragranceindex_ai) is linked to the IG Business Account before running hashtag queries.

### `public_profile`
Standard permission confirming the app user's basic identity. Required as part of the baseline app access flow.

---

## 3. Reviewer Instruction Flow

Provide these instructions in the Meta App Review form for the reviewer:

```
1. Visit: https://fragranceindex.ai/admin/meta-review/instagram
   (This route requires admin login — use the test account credentials
   provided in the "Test User" section of this submission.)

2. Click "Check Connection" to verify that the Instagram Business Account
   (fragranceindex_ai, ID: 17841426873066676) is accessible via the app.

3. Select a hashtag from the dropdown (e.g., #perfume or #fragrance).

4. Click "Run Hashtag Demo" to see the live API calls:
   - Step 1: ig_hashtag_search → resolves #perfume to an IG Hashtag ID
   - Step 2: /{hashtag_id}/recent_media → returns public posts

5. Observe the returned sample: caption preview, timestamp, permalink,
   media type, and like count. Note that:
   - No usernames or profile data are shown (not available from this endpoint)
   - No raw content is exposed on public pages
   - The access token is never visible in the UI

6. The explanation on the page describes how FragranceIndex.ai uses this
   data to generate aggregated fragrance trend intelligence.
```

---

## 4. Screencast Storyboard

Record approximately 2-3 minutes covering:

### Scene 1 — App context (15s)
- Open `https://fragranceindex.ai` (public landing page)
- Briefly show: "FragranceIndex.ai is a fragrance market intelligence platform"
- Narrate: "We track fragrance trends from social media, including Instagram public hashtag content"

### Scene 2 — Login (15s)
- Click "Sign in" → enter admin credentials → authenticate
- No need to show password entry in detail

### Scene 3 — Navigate to demo route (10s)
- From authenticated state: navigate to `/admin/meta-review/instagram`
- Show the admin console loading

### Scene 4 — Check Connection (20s)
- Click "Check Connection"
- Show: "Instagram Business Account Connected" with username `@fragranceindex_ai` and account ID
- Narrate: "The app is connected to our Instagram Business Account via the Facebook Page relationship"

### Scene 5 — Hashtag demo (60s)
- Select `#perfume` from the dropdown
- Click "Run Hashtag Demo"
- Show: hashtag ID resolved, 5 public posts returned
- Narrate: "The app queries the Instagram Hashtag Search API to find public fragrance posts. We retrieve caption text, timestamp, permalink, and engagement signals."
- Point out the caption previews in the results
- Show the "How we use this" note at the bottom

### Scene 6 — Second hashtag (optional, 30s)
- Switch to `#nicheperfume`
- Click "Run Hashtag Demo" again
- Show results (different posts)
- Narrate: "We monitor multiple fragrance hashtags to build cross-signal intelligence"

### Scene 7 — Closing (15s)
- Scroll to "API Endpoints Used" section at the bottom
- Narrate: "The platform uses only the Hashtag Search and Recent Media endpoints. No user data is collected, stored in profiles, or exposed publicly."
- End recording

---

## 5. Suggested Text for Meta App Review Permission Descriptions

Edit these before submission. These are starting points.

---

### Instagram Public Content Access

**Describe how your app uses this feature:**

```
FragranceIndex.ai is a fragrance market intelligence platform. We use Instagram 
Public Content Access to retrieve public posts associated with fragrance-related 
hashtags (e.g., #perfume, #fragrance, #nicheperfume) via the Hashtag Search API.

Specifically, the app:
1. Calls GET /ig_hashtag_search to resolve a hashtag text (e.g., "perfume") to 
   an IG Hashtag Object ID.
2. Calls GET /{hashtag_id}/recent_media to retrieve public posts with fields: 
   id, caption, timestamp, permalink, media_type, like_count.
3. Processes caption text internally to extract fragrance entity mentions (perfume 
   names, brands) using our entity resolution engine.
4. Aggregates these signals into trend scores and momentum indicators for the 
   fragrance market.

Raw Instagram post content is never exposed publicly. It is processed internally 
and only aggregated intelligence (e.g., "Creed Aventus — Rising trend") is 
surfaced to authenticated platform users.

We query a curated list of 6 fragrance hashtags (far below the 30-hashtag 7-day 
limit). The access token and Business Account ID are stored in server-side 
environment variables only — never transmitted to the browser.
```

---

### `instagram_basic`

**Describe how your app uses this permission:**

```
instagram_basic is required as the baseline for all Instagram Graph API operations.
It allows the app to read basic account information from our connected Instagram 
Business Account (fragranceindex_ai), which is the prerequisite for performing 
Hashtag Search queries. We do not use this permission to read end-user data.
```

---

### `pages_read_engagement`

**Describe how your app uses this permission:**

```
pages_read_engagement is required to establish the Facebook Page → Instagram 
Business Account relationship needed for the Hashtag Search API. The user_id 
parameter in ig_hashtag_search must reference an IG Business Account, which in 
turn must be connected to a Facebook Page that is managed by the app. We use this 
permission to confirm the Page → IG Account linkage, not to read Page engagement 
analytics for any other purpose.
```

---

### `pages_show_list`

**Describe how your app uses this permission:**

```
pages_show_list is required to enumerate the Facebook Pages connected to our 
developer app. We use it to confirm that the fragranceindex_ai Facebook Page is 
correctly linked to our Instagram Business Account (ID: 17841426873066676) before 
running hashtag queries. We do not use this permission to access any other pages 
or page content.
```

---

### `public_profile`

**Describe how your app uses this permission:**

```
public_profile is used for basic app user identity confirmation during the 
authentication flow. It is a standard baseline permission and is not used to 
collect or store end-user personal profile data.
```

---

## 6. Platform Policy Confirmations

When Meta asks policy confirmation questions, confirm:

- **Do you use the data to build user profiles?** No. We process public hashtag content to generate aggregated fragrance trend signals. We do not build profiles of Instagram users.
- **Do you sell or share user data?** No. Aggregated trend intelligence is surfaced to authenticated FragranceIndex.ai users only (industry professionals). No raw content or user-identifiable data is sold or shared.
- **Do you store the data?** Caption text is stored temporarily for internal entity resolution. We do not store user identifiers (usernames are not available from the Hashtag Search API response). Processed trend data is retained; raw content follows our data retention policy.
- **Do you expose the data publicly?** No. Public pages at fragranceindex.ai show only aggregated trend intelligence (scores, direction, topic signals), never raw Instagram content.

---

## 7. Test Account for Reviewer

The reviewer needs an account to access `/admin/meta-review/instagram`.

**Options:**
1. Create a dedicated reviewer test account in Supabase (`Authentication → Users → Invite User`)
2. Add the reviewer's email to `ADMIN_EMAILS` Railway env var temporarily
3. Or provide a screen recording without requiring reviewer login (Meta accepts screencast-only demos)

**Recommended:** Option 3 (screencast only) is safest — no need to create reviewer accounts or temporarily expand admin access.

---

## 8. Business Verification Note

Business Verification is currently "In review" with Meta. Some permissions (including Instagram Public Content Access) may require Business Verification to be approved before App Review can be completed.

**If App Review is blocked pending Business Verification:**
- Continue building the demo flow (already done in IG1-R)
- Monitor Business Verification status in Meta Business Suite
- Submit App Review immediately after Business Verification is approved
- Do not attempt production ingestion before App Review approval

---

## 9. Post-Approval Checklist (complete after Meta approves)

```
[ ] App Review approved for Instagram Public Content Access
[ ] Business Verification confirmed in Meta Business Suite
[ ] Generate long-lived access token (exchange short-lived via fb_exchange_token)
[ ] Set INSTAGRAM_ACCESS_TOKEN in Railway env (generous-prosperity backend service)
[ ] Set INSTAGRAM_BUSINESS_ACCOUNT_ID=17841426873066676 in Railway env
[ ] Run Gate 0 verification test (see docs/architecture/INSTAGRAM_INGESTION.md §5)
[ ] If Gate 0 PASS: proceed to full IG1 implementation (migration 044, ingest job, normalizer)
[ ] Update CLAUDE.md IG1 status to PRODUCTION VERIFIED
```
