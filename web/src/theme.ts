export const theme = {
  colors: {
    background: {
      canvas: '#0B0E14',
      surface: '#111620',
      elevated: '#171D29',
      muted: '#202838',
    },
    border: {
      subtle: '#252E3D',
      strong: '#364155',
    },
    text: {
      primary: '#F2F5F9',
      secondary: '#9CA8B8',
      muted: '#687487',
    },
    accent: {
      amber: '#F2A900',
      amberSoft: '#3A2B0A',
    },
    market: {
      up: '#F04444',
      down: '#20B26B',
      flat: '#9CA8B8',
    },
  },
  typography: {
    fontFamily: {
      sans: '"Inter", "PingFang SC", "Microsoft YaHei", sans-serif',
      mono: '"JetBrains Mono", "SFMono-Regular", Consolas, monospace',
    },
  },
  radius: {
    small: '4px',
    medium: '8px',
    large: '12px',
  },
  spacing: {
    xs: '4px',
    sm: '8px',
    md: '16px',
    lg: '24px',
    xl: '32px',
  },
} as const

export type Theme = typeof theme
