import React from 'react';
import type { Metadata } from 'next';
import { GOOGLE_FONTS_STYLESHEET_URL } from '@/lib/adPresetsServer';
import './globals.css';

export const metadata: Metadata = {
  title: 'Veo 3.1 · Localized AI Video Ad Studio (Non-English D2C)',
  description:
    'Dark-mode creator studio for non-English D2C video ads (Urdu Nastaliq RTL, Arabic RTL, Hindi Devanagari, English) powered by Vertex AI Veo 3.1, Remotion, and Supabase Credit Ledger.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>): React.ReactElement {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link rel="stylesheet" href={GOOGLE_FONTS_STYLESHEET_URL} />
      </head>
      <body className="bg-[#09090B] text-[#FAFAFA] antialiased">
        {children}
      </body>
    </html>
  );
}
