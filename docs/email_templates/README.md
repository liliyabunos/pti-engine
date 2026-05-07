# FTI Market Terminal — Email Templates

## Magic Link Email

Files:
- `magic_link_fti.html` — HTML email template (Gmail-safe, inline styles, table layout)
- `magic_link_fti.txt` — Plain text fallback

### Provider

Email is sent by **Supabase Auth** directly. There is no backend email sending in this project for magic links — `signInWithOtp` delegates entirely to Supabase's transactional email.

The template must be applied in the **Supabase Dashboard**, not in code.

### Placeholder

Supabase uses Go template syntax. The magic link URL placeholder is:

```
{{ .ConfirmationURL }}
```

This is used in both the `href` attribute of the CTA button and the plain-text fallback link. Do not change it.

### How to apply

1. Go to [Supabase Dashboard](https://supabase.com/dashboard) → select the project → **Authentication** → **Email Templates**

2. Select the **Magic Link** template type.

3. **Subject line** — set to:
   ```
   Your Magic Link — FTI Market Terminal
   ```

4. **HTML body** — paste the full contents of `magic_link_fti.html`.

5. **Plain text body** — paste the full contents of `magic_link_fti.txt`.

6. Click **Save**.

7. **Sender display name** — go to **Authentication** → **SMTP Settings** (or **Email** section) and set the "Sender name" to:
   ```
   FTI Market Terminal
   ```
   The sender address should remain whatever is configured (e.g. noreply@fragranceindex.ai or the Supabase default).

### Verification checklist

After applying:
- [ ] Send a test magic link to your own email
- [ ] Confirm subject shows "FTI Market Terminal" (not "PTI Market Terminal")
- [ ] Confirm HTML renders dark card with amber button in Gmail
- [ ] Click the button — confirm redirect lands on fragranceindex.ai/auth/callback
- [ ] Confirm login completes successfully (session established, dashboard loads)
- [ ] Confirm no old Railway URL (`pti-frontend-production.up.railway.app`) appears in the email
- [ ] Confirm no "PTI" user-visible text in the email body

### Design tokens used

| Element | Color | Hex |
|---------|-------|-----|
| Page background | zinc-950 | `#09090b` |
| Card background | zinc-900 | `#18181b` |
| Footer background | ~zinc-925 | `#111113` |
| Border | zinc-800 | `#27272a` |
| Primary text | zinc-100 | `#f4f4f5` |
| Secondary text | zinc-400 | `#a1a1aa` |
| Muted text | zinc-500/600 | `#71717a` / `#52525b` |
| Amber accent (bar, button, link) | amber-500 | `#f59e0b` |
| FTI badge background | amber-400 | `#fbbf24` |
| Badge text / button text | zinc-950 | `#09090b` |
