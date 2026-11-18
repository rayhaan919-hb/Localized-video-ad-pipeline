import React from 'react';
import type { Metadata } from 'next';
import { GOOGLE_FONTS_STYLESHEET_URL } from '@/lib/adPresetsServer';
import './globals.css';

export const metadata: Metadata = {
  title: 'Localized Video Ad Studio',
  description:
    'Warm creator studio for localized D2C video ads (Urdu Nastaliq RTL, Arabic RTL, Hindi Devanagari, English) powered by Remotion.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>): React.ReactElement {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link rel="stylesheet" href={GOOGLE_FONTS_STYLESHEET_URL} />
      </head>
      <body className="bg-[#FAF7F2] text-[#1C1917] antialiased">
        {children}
      </body>
    </html>
  );
}
