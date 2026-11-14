import React from 'react';
import { Composition, type CalculateMetadataFunction } from 'remotion';
import { getPresetAdProps } from './presets';
import { VERTICAL_AD_CONFIG } from './types';
import { VerticalAdTemplate } from './VerticalAdTemplate';

const resolveAdMetadata: CalculateMetadataFunction<Record<string, unknown>> = ({ props }) => {
  const customFrames = props.durationInFrames;
  const durationInFrames =
    typeof customFrames === 'number' && Number.isFinite(customFrames)
      ? Math.max(30, Math.min(450, Math.round(customFrames)))
      : VERTICAL_AD_CONFIG.durationInFrames;

  return {
    durationInFrames,
    fps: VERTICAL_AD_CONFIG.fps,
    width: VERTICAL_AD_CONFIG.width,
    height: VERTICAL_AD_CONFIG.height,
  };
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="VerticalAd-UR"
        component={VerticalAdTemplate}
        durationInFrames={VERTICAL_AD_CONFIG.durationInFrames}
        fps={VERTICAL_AD_CONFIG.fps}
        width={VERTICAL_AD_CONFIG.width}
        height={VERTICAL_AD_CONFIG.height}
        calculateMetadata={resolveAdMetadata}
        defaultProps={getPresetAdProps('ur', 'problem_solution')}
      />
      <Composition
        id="VerticalAd-AR"
        component={VerticalAdTemplate}
        durationInFrames={VERTICAL_AD_CONFIG.durationInFrames}
        fps={VERTICAL_AD_CONFIG.fps}
        width={VERTICAL_AD_CONFIG.width}
        height={VERTICAL_AD_CONFIG.height}
        calculateMetadata={resolveAdMetadata}
        defaultProps={getPresetAdProps('ar', 'problem_solution')}
      />
      <Composition
        id="VerticalAd-HI"
        component={VerticalAdTemplate}
        durationInFrames={VERTICAL_AD_CONFIG.durationInFrames}
        fps={VERTICAL_AD_CONFIG.fps}
        width={VERTICAL_AD_CONFIG.width}
        height={VERTICAL_AD_CONFIG.height}
        calculateMetadata={resolveAdMetadata}
        defaultProps={getPresetAdProps('hi', 'problem_solution')}
      />
      <Composition
        id="VerticalAd-EN"
        component={VerticalAdTemplate}
        durationInFrames={VERTICAL_AD_CONFIG.durationInFrames}
        fps={VERTICAL_AD_CONFIG.fps}
        width={VERTICAL_AD_CONFIG.width}
        height={VERTICAL_AD_CONFIG.height}
        calculateMetadata={resolveAdMetadata}
        defaultProps={getPresetAdProps('en', 'problem_solution')}
      />
    </>
  );
};

export const VerticalAdRoot = RemotionRoot;
