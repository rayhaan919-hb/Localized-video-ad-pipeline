import React from 'react';
import { Composition } from 'remotion';
import { getPresetAdProps } from './presets';
import { VERTICAL_AD_CONFIG } from './types';
import { VerticalAdTemplate } from './VerticalAdTemplate';

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
        defaultProps={getPresetAdProps('ur', 'problem_solution')}
      />
      <Composition
        id="VerticalAd-AR"
        component={VerticalAdTemplate}
        durationInFrames={VERTICAL_AD_CONFIG.durationInFrames}
        fps={VERTICAL_AD_CONFIG.fps}
        width={VERTICAL_AD_CONFIG.width}
        height={VERTICAL_AD_CONFIG.height}
        defaultProps={getPresetAdProps('ar', 'problem_solution')}
      />
      <Composition
        id="VerticalAd-HI"
        component={VerticalAdTemplate}
        durationInFrames={VERTICAL_AD_CONFIG.durationInFrames}
        fps={VERTICAL_AD_CONFIG.fps}
        width={VERTICAL_AD_CONFIG.width}
        height={VERTICAL_AD_CONFIG.height}
        defaultProps={getPresetAdProps('hi', 'problem_solution')}
      />
      <Composition
        id="VerticalAd-EN"
        component={VerticalAdTemplate}
        durationInFrames={VERTICAL_AD_CONFIG.durationInFrames}
        fps={VERTICAL_AD_CONFIG.fps}
        width={VERTICAL_AD_CONFIG.width}
        height={VERTICAL_AD_CONFIG.height}
        defaultProps={getPresetAdProps('en', 'problem_solution')}
      />
    </>
  );
};

export const VerticalAdRoot = RemotionRoot;
