-- 003: Google OAuth 2.0 Identity Linking
-- Adds auth_provider and unique nullable google_sub column to public.users.

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS auth_provider TEXT NOT NULL DEFAULT 'password',
  ADD COLUMN IF NOT EXISTS google_sub TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub_unique
  ON public.users (google_sub)
  WHERE google_sub IS NOT NULL;

INSERT INTO public.schema_migrations (version)
VALUES ('003_google_oauth_identity')
ON CONFLICT (version) DO NOTHING;
