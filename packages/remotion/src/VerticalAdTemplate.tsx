import React from 'react';
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import { GOOGLE_FONTS_STYLESHEET_URL, getLanguageFontMeta } from './fonts';
import { getPresetAdProps } from './presets';
import {
  DESIGN_TOKENS,
  type CaptionSegment,
  type LocalizedAdProps,
} from './types';

function renderHighlightedCaption(
  segment: CaptionSegment,
  highlightScale: number
): React.ReactNode {
  const { text, highlightWord } = segment;
  if (!highlightWord || !text.includes(highlightWord)) {
    return text;
  }

  const index = text.indexOf(highlightWord);
  const before = text.slice(0, index);
  const after = text.slice(index + highlightWord.length);

  return (
    <>
      {before}
      <span
        style={{
          display: 'inline-block',
          backgroundColor: DESIGN_TOKENS.accentPrimary,
          color: DESIGN_TOKENS.textPrimary,
          padding: '4px 12px',
          margin: '0 4px',
          borderRadius: '8px',
          border: `1px solid ${DESIGN_TOKENS.textPrimary}`,
          transform: `scale(${highlightScale.toFixed(3)})`,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {highlightWord}
      </span>
      {after}
    </>
  );
}

export const VerticalAdTemplate: React.FC<Partial<LocalizedAdProps>> = (
  rawProps
) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();

  const language = rawProps.language ?? 'ur';
  const adAngle = rawProps.adAngle ?? 'problem_solution';
  const props: LocalizedAdProps = getPresetAdProps(language, adAngle, rawProps);
  const meta = getLanguageFontMeta(props.language);

  // Animations driven by Remotion's spring() and interpolate()
  const headerEntrance = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 140, mass: 0.8 },
  });

  const hookEntrance = spring({
    frame: Math.max(0, frame - 3),
    fps,
    config: { damping: 14, stiffness: 120, mass: 0.9 },
  });

  const dockEntrance = spring({
    frame: Math.max(0, frame - 6),
    fps,
    config: { damping: 16, stiffness: 130, mass: 0.9 },
  });

  // Active caption lookup across the timeline
  const safeCaptions =
    props.captions && props.captions.length > 0
      ? props.captions
      : getPresetAdProps(props.language, props.adAngle).captions;

  const activeCaptionIndex = Math.max(
    0,
    safeCaptions.findIndex(
      (seg) => frame >= seg.startFrame && frame < seg.endFrame
    )
  );
  const activeCaption: CaptionSegment =
    safeCaptions[activeCaptionIndex] ??
    safeCaptions[safeCaptions.length - 1] ?? {
      id: 'fallback-caption',
      text: props.hookText,
      startFrame: 0,
      endFrame: durationInFrames,
    };

  const segmentLocalFrame = Math.max(0, frame - activeCaption.startFrame);
  const captionSpring = spring({
    frame: segmentLocalFrame,
    fps,
    config: { damping: 15, stiffness: 160, mass: 0.7 },
  });

  const highlightPulse = interpolate(
    segmentLocalFrame,
    [0, 6, 14],
    [0.94, 1.05, 1.0],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }
  );

  const showcaseFloatY = interpolate(
    frame,
    [0, durationInFrames / 2, durationInFrames],
    [0, -12, 0],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }
  );

  const timelineProgressPct = interpolate(
    frame,
    [0, Math.max(1, durationInFrames - 1)],
    [0, 100],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }
  );

  const ctaPulseScale = interpolate(
    frame % 30,
    [0, 15, 30],
    [1, 1.018, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    }
  );

  const paddedFrame = String(frame).padStart(2, '0');
  const paddedDuration = String(durationInFrames).padStart(2, '0');

  return (
    <AbsoluteFill
      style={{
        backgroundColor: DESIGN_TOKENS.bgCanvas,
        color: DESIGN_TOKENS.textPrimary,
        fontFamily: DESIGN_TOKENS.fontUi,
        overflow: 'hidden',
      }}
    >
      {/* Load Google Fonts for Urdu Nastaliq, Arabic, Devanagari, Inter & JetBrains Mono */}
      <link rel="stylesheet" href={GOOGLE_FONTS_STYLESHEET_URL} />

      {/* Layer 1: Tonal Dark Studio Canvas Fallback (always rendered behind video) */}
      <AbsoluteFill
        style={{
          backgroundColor: DESIGN_TOKENS.bgCanvas,
          padding: '32px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
        }}
      >
        {/* Crisp Architectural Grid Frame (1px solid #27272A, no AI clutter) */}
        <div
          style={{
            position: 'absolute',
            inset: '24px',
            border: `1px solid ${DESIGN_TOKENS.borderDark}`,
            borderRadius: '24px',
            pointerEvents: 'none',
          }}
        />

        {/* Center Studio Showcase Stage */}
        <div
          style={{
            width: '952px',
            height: '720px',
            backgroundColor: DESIGN_TOKENS.bgSurface,
            border: `1px solid ${DESIGN_TOKENS.borderDark}`,
            borderRadius: '24px',
            padding: '32px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            transform: `translateY(${showcaseFloatY.toFixed(2)}px)`,
          }}
        >
          {/* Stage Top Telemetry Row */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderBottom: `1px solid ${DESIGN_TOKENS.borderDark}`,
              paddingBottom: '16px',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                fontFamily: DESIGN_TOKENS.fontMono,
                fontSize: '20px',
                color: DESIGN_TOKENS.textMuted,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              <span
                style={{
                  width: '12px',
                  height: '12px',
                  borderRadius: '4px',
                  backgroundColor: DESIGN_TOKENS.accentPrimary,
                  display: 'inline-block',
                }}
              />
              <span>VEO-3.1 STUDIO STAGE · {meta.regionLabel}</span>
            </div>
            <div
              style={{
                fontFamily: DESIGN_TOKENS.fontMono,
                fontSize: '20px',
                color: DESIGN_TOKENS.textPrimary,
                backgroundColor: DESIGN_TOKENS.bgCanvas,
                border: `1px solid ${DESIGN_TOKENS.borderDark}`,
                padding: '8px 16px',
                borderRadius: '8px',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {width}×{height} · {fps}FPS
            </div>
          </div>

          {/* Center Product Showcase Visual */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '32px',
              padding: '24px 0',
              direction: meta.dir,
            }}
          >
            {/* Minimalist Product Pedestal Card */}
            <div
              style={{
                width: '340px',
                height: '420px',
                backgroundColor: DESIGN_TOKENS.bgCanvas,
                border: `1px solid ${DESIGN_TOKENS.borderDark}`,
                borderRadius: '16px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '24px',
                position: 'relative',
                flexShrink: 0,
              }}
            >
              {props.productImageUrl ? (
                <Img
                  src={props.productImageUrl}
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'contain',
                    borderRadius: '12px',
                  }}
                />
              ) : (
                <>
                  {/* Crisp Geometric Dropper Bottle Vector */}
                  <svg
                    width="160"
                    height="260"
                    viewBox="0 0 160 260"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <rect
                      x="64"
                      y="12"
                      width="32"
                      height="36"
                      rx="8"
                      fill="#18181B"
                      stroke="#FAFAFA"
                      strokeWidth="3"
                    />
                    <rect
                      x="52"
                      y="48"
                      width="56"
                      height="24"
                      rx="4"
                      fill="#6366F1"
                    />
                    <rect
                      x="32"
                      y="80"
                      width="96"
                      height="156"
                      rx="20"
                      fill="#18181B"
                      stroke="#FAFAFA"
                      strokeWidth="3"
                    />
                    <rect
                      x="44"
                      y="112"
                      width="72"
                      height="88"
                      rx="8"
                      fill="#09090B"
                      stroke="#6366F1"
                      strokeWidth="2"
                    />
                    <line
                      x1="56"
                      y1="140"
                      x2="104"
                      y2="140"
                      stroke="#FAFAFA"
                      strokeWidth="3"
                    />
                    <line
                      x1="56"
                      y1="160"
                      x2="92"
                      y2="160"
                      stroke="#A1A1AA"
                      strokeWidth="2"
                    />
                    <circle cx="80" cy="182" r="6" fill="#6366F1" />
                  </svg>
                  <div
                    style={{
                      marginTop: '16px',
                      fontFamily: DESIGN_TOKENS.fontMono,
                      fontSize: '18px',
                      color: DESIGN_TOKENS.textMuted,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    30ML · C20 ACTIVE
                  </div>
                </>
              )}
            </div>

            {/* Product Spec Highlights */}
            <div
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                gap: '16px',
                textAlign: meta.isRtl ? 'right' : 'left',
              }}
            >
              <div
                style={{
                  display: 'inline-flex',
                  alignSelf: meta.isRtl ? 'flex-end' : 'flex-start',
                  backgroundColor: DESIGN_TOKENS.bgCanvas,
                  border: `1px solid ${DESIGN_TOKENS.accentPrimary}`,
                  color: DESIGN_TOKENS.textPrimary,
                  padding: '8px 16px',
                  borderRadius: '8px',
                  fontFamily: meta.fontStack,
                  fontSize: '22px',
                  lineHeight: meta.lineHeight,
                }}
              >
                {meta.verifiedD2cLabel}
              </div>

              <div
                style={{
                  fontFamily: meta.fontStack,
                  fontSize: '40px',
                  fontWeight: 700,
                  lineHeight: meta.lineHeight,
                  color: DESIGN_TOKENS.textPrimary,
                }}
              >
                {props.productTitle}
              </div>

              <div
                style={{
                  display: 'flex',
                  flexDirection: 'row',
                  gap: '12px',
                  flexWrap: 'wrap',
                }}
              >
                <div
                  style={{
                    backgroundColor: DESIGN_TOKENS.bgCanvas,
                    border: `1px solid ${DESIGN_TOKENS.borderDark}`,
                    padding: '12px 16px',
                    borderRadius: '8px',
                    fontFamily: DESIGN_TOKENS.fontMono,
                    fontSize: '24px',
                    fontWeight: 700,
                    color: DESIGN_TOKENS.textPrimary,
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {props.priceDisplay}
                </div>
                {props.discountBadge ? (
                  <div
                    style={{
                      backgroundColor: DESIGN_TOKENS.accentPrimary,
                      padding: '12px 16px',
                      borderRadius: '8px',
                      fontFamily: DESIGN_TOKENS.fontMono,
                      fontSize: '22px',
                      fontWeight: 700,
                      color: DESIGN_TOKENS.textPrimary,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {props.discountBadge}
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {/* Stage Bottom Spec Bar */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderTop: `1px solid ${DESIGN_TOKENS.borderDark}`,
              paddingTop: '16px',
              fontFamily: DESIGN_TOKENS.fontMono,
              fontSize: '18px',
              color: DESIGN_TOKENS.textMuted,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            <span>SCRIPT DIR: {meta.dir.toUpperCase()}</span>
            <span>FONT: {meta.fontFamily.toUpperCase()}</span>
            <span>
              FRAME {paddedFrame}/{paddedDuration}
            </span>
          </div>
        </div>
      </AbsoluteFill>

      {/* Layer 2: Optional External / Mock MP4 Video Background */}
      {props.videoSrc ? (
        <AbsoluteFill>
          <OffthreadVideo
            src={props.videoSrc}
            muted
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'cover',
            }}
          />
          <div
            style={{
              position: 'absolute',
              inset: 0,
              backgroundColor: 'rgba(9, 9, 11, 0.45)',
            }}
          />
        </AbsoluteFill>
      ) : null}

      {/* Layer 3: Foreground 9:16 D2C Ad Overlays */}
      <AbsoluteFill
        style={{
          padding: '32px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        {/* TOP SECTION: Brand Pill + Angle Badge + RTL/LTR Hook Banner */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '24px',
          }}
        >
          {/* Top Progress Bar (4px height) */}
          <div
            style={{
              width: '100%',
              height: '4px',
              backgroundColor: DESIGN_TOKENS.borderDark,
              borderRadius: '4px',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${timelineProgressPct.toFixed(1)}%`,
                height: '100%',
                backgroundColor: DESIGN_TOKENS.accentPrimary,
              }}
            />
          </div>

          {/* Top D2C Brand Header Row */}
          <div
            dir={meta.dir}
            style={{
              display: 'flex',
              flexDirection: 'row',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: '16px',
              opacity: headerEntrance,
              transform: `translateY(${interpolate(
                headerEntrance,
                [0, 1],
                [-20, 0]
              ).toFixed(2)}px)`,
            }}
          >
            {/* Brand Pill */}
            <div
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                gap: '12px',
                backgroundColor: DESIGN_TOKENS.bgSurface,
                border: `1px solid ${DESIGN_TOKENS.borderDark}`,
                padding: '12px 24px',
                borderRadius: '12px',
              }}
            >
              <span
                style={{
                  width: '12px',
                  height: '12px',
                  borderRadius: '4px',
                  backgroundColor: DESIGN_TOKENS.accentPrimary,
                  display: 'inline-block',
                }}
              />
              <span
                style={{
                  fontFamily: DESIGN_TOKENS.fontUi,
                  fontSize: '26px',
                  fontWeight: 700,
                  color: DESIGN_TOKENS.textPrimary,
                }}
              >
                {props.brandName}
              </span>
            </div>

            {/* Angle Tag & Discount Badge */}
            <div
              style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                gap: '12px',
              }}
            >
              <div
                style={{
                  backgroundColor: DESIGN_TOKENS.bgSurface,
                  border: `1px solid ${DESIGN_TOKENS.borderDark}`,
                  padding: '12px 24px',
                  borderRadius: '12px',
                  fontFamily: meta.fontStack,
                  fontSize: '24px',
                  fontWeight: 600,
                  lineHeight: meta.lineHeight,
                  color: DESIGN_TOKENS.textMuted,
                }}
              >
                {meta.angleLabels[props.adAngle]}
              </div>

              {props.discountBadge ? (
                <div
                  style={{
                    backgroundColor: DESIGN_TOKENS.accentPrimary,
                    border: `1px solid ${DESIGN_TOKENS.accentPrimary}`,
                    padding: '12px 24px',
                    borderRadius: '12px',
                    fontFamily: DESIGN_TOKENS.fontMono,
                    fontSize: '24px',
                    fontWeight: 700,
                    color: DESIGN_TOKENS.textPrimary,
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {props.discountBadge}
                </div>
              ) : null}
            </div>
          </div>

          {/* Animated RTL/LTR Hook Headline Banner */}
          <div
            dir={meta.isRtl ? 'rtl' : 'ltr'}
            style={{
              backgroundColor: DESIGN_TOKENS.bgSurface,
              border: `1px solid ${DESIGN_TOKENS.borderDark}`,
              borderRight: meta.isRtl
                ? `8px solid ${DESIGN_TOKENS.accentPrimary}`
                : `1px solid ${DESIGN_TOKENS.borderDark}`,
              borderLeft: meta.isRtl
                ? `1px solid ${DESIGN_TOKENS.borderDark}`
                : `8px solid ${DESIGN_TOKENS.accentPrimary}`,
              borderRadius: '16px',
              padding: '24px 32px',
              opacity: hookEntrance,
              transform: `translateY(${interpolate(
                hookEntrance,
                [0, 1],
                [24, 0]
              ).toFixed(2)}px)`,
              textAlign: meta.isRtl ? 'right' : 'left',
            }}
          >
            <div
              style={{
                fontFamily: meta.fontStack,
                fontSize: meta.language === 'ur' ? '44px' : '46px',
                fontWeight: 700,
                lineHeight: meta.hookLineHeight,
                letterSpacing: meta.letterSpacing,
                wordSpacing: meta.wordSpacing,
                color: DESIGN_TOKENS.textPrimary,
              }}
            >
              {props.hookText}
            </div>
          </div>
        </div>

        {/* BOTTOM SECTION: Synchronized Animated Captions + Product Price Dock & CTA */}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '24px',
          }}
        >
          {/* Synchronized Animated Caption Box */}
          <div
            dir={meta.dir}
            style={{
              backgroundColor: DESIGN_TOKENS.bgSurface,
              border: `1px solid ${DESIGN_TOKENS.borderDark}`,
              borderRadius: '16px',
              padding: '24px 32px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
              transform: `translateY(${interpolate(
                captionSpring,
                [0, 1],
                [16, 0]
              ).toFixed(2)}px)`,
              opacity: interpolate(captionSpring, [0, 1], [0.4, 1]),
            }}
          >
            {/* Caption Header Telemetry */}
            <div
              style={{
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                borderBottom: `1px solid ${DESIGN_TOKENS.borderDark}`,
                paddingBottom: '12px',
              }}
            >
              <span
                style={{
                  fontFamily: DESIGN_TOKENS.fontMono,
                  fontSize: '20px',
                  color: DESIGN_TOKENS.accentPrimary,
                  fontWeight: 600,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                CAPTION · {activeCaptionIndex + 1}/{safeCaptions.length}
              </span>
              <span
                style={{
                  fontFamily: DESIGN_TOKENS.fontMono,
                  fontSize: '20px',
                  color: DESIGN_TOKENS.textMuted,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {activeCaption.startFrame}F–{activeCaption.endFrame}F
              </span>
            </div>

            {/* Active Caption Text with Highlight Pill */}
            <div
              style={{
                fontFamily: meta.fontStack,
                fontSize: meta.language === 'ur' ? '42px' : '44px',
                fontWeight: 700,
                lineHeight: meta.captionLineHeight,
                letterSpacing: meta.letterSpacing,
                wordSpacing: meta.wordSpacing,
                color: DESIGN_TOKENS.textPrimary,
                textAlign: meta.isRtl ? 'right' : 'left',
              }}
            >
              {renderHighlightedCaption(activeCaption, highlightPulse)}
            </div>
          </div>

          {/* Bottom Dock: Product Price Card + High-Contrast Indigo CTA Bar */}
          <div
            dir={meta.dir}
            style={{
              backgroundColor: DESIGN_TOKENS.bgSurface,
              border: `1px solid ${DESIGN_TOKENS.borderDark}`,
              borderRadius: '24px',
              padding: '32px',
              display: 'flex',
              flexDirection: 'column',
              gap: '24px',
              opacity: dockEntrance,
              transform: `translateY(${interpolate(
                dockEntrance,
                [0, 1],
                [28, 0]
              ).toFixed(2)}px)`,
            }}
          >
            {/* Product Info & Price Telemetry Row */}
            <div
              style={{
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '24px',
              }}
            >
              {/* Product Title & COD Badge */}
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '8px',
                  flex: 1,
                  textAlign: meta.isRtl ? 'right' : 'left',
                }}
              >
                <div
                  style={{
                    fontFamily: meta.fontStack,
                    fontSize: '24px',
                    color: DESIGN_TOKENS.textMuted,
                    lineHeight: meta.lineHeight,
                  }}
                >
                  {meta.codBadgeLabel}
                </div>
                <div
                  style={{
                    fontFamily: meta.fontStack,
                    fontSize: '34px',
                    fontWeight: 700,
                    color: DESIGN_TOKENS.textPrimary,
                    lineHeight: meta.lineHeight,
                  }}
                >
                  {props.productTitle}
                </div>
              </div>

              {/* Price Box (JetBrains Mono + tabular-nums) */}
              <div
                style={{
                  backgroundColor: DESIGN_TOKENS.bgCanvas,
                  border: `1px solid ${DESIGN_TOKENS.borderDark}`,
                  borderRadius: '16px',
                  padding: '16px 24px',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: meta.isRtl ? 'flex-start' : 'flex-end',
                  gap: '4px',
                  flexShrink: 0,
                }}
              >
                <span
                  style={{
                    fontFamily: meta.fontStack,
                    fontSize: '20px',
                    color: DESIGN_TOKENS.textMuted,
                    lineHeight: meta.lineHeight,
                  }}
                >
                  {meta.priceLabel}
                </span>
                <span
                  style={{
                    fontFamily: DESIGN_TOKENS.fontMono,
                    fontSize: '40px',
                    fontWeight: 700,
                    color: DESIGN_TOKENS.textPrimary,
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {props.priceDisplay}
                </span>
                {props.originalPriceDisplay ? (
                  <span
                    style={{
                      fontFamily: DESIGN_TOKENS.fontMono,
                      fontSize: '22px',
                      color: DESIGN_TOKENS.textMuted,
                      textDecoration: 'line-through',
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {props.originalPriceDisplay}
                  </span>
                ) : null}
              </div>
            </div>

            {/* High-Contrast Indigo (#6366F1) CTA Bar */}
            <div
              style={{
                backgroundColor: DESIGN_TOKENS.accentPrimary,
                border: `1px solid ${DESIGN_TOKENS.accentPrimary}`,
                borderRadius: '16px',
                padding: '24px 32px',
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                transform: `scale(${ctaPulseScale.toFixed(3)})`,
              }}
            >
              <span
                style={{
                  fontFamily: meta.fontStack,
                  fontSize: meta.language === 'ur' ? '34px' : '36px',
                  fontWeight: 700,
                  lineHeight: meta.lineHeight,
                  color: DESIGN_TOKENS.textPrimary,
                }}
              >
                {props.ctaText}
              </span>
              <span
                style={{
                  backgroundColor: DESIGN_TOKENS.bgCanvas,
                  color: DESIGN_TOKENS.textPrimary,
                  border: `1px solid ${DESIGN_TOKENS.borderDark}`,
                  borderRadius: '12px',
                  padding: '8px 16px',
                  fontFamily: DESIGN_TOKENS.fontMono,
                  fontSize: '28px',
                  fontWeight: 700,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {meta.isRtl ? '←' : '→'}
              </span>
            </div>

            {/* Bottom Monospace Telemetry Strip */}
            <div
              style={{
                display: 'flex',
                flexDirection: 'row',
                justifyContent: 'space-between',
                alignItems: 'center',
                fontFamily: DESIGN_TOKENS.fontMono,
                fontSize: '18px',
                color: DESIGN_TOKENS.textMuted,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              <span>ID: {props.jobId ?? 'job_preview_001'}</span>
              <span>
                LANG: {props.language.toUpperCase()} ({meta.dir.toUpperCase()})
              </span>
              <span>CURRENCY: {props.currency}</span>
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
