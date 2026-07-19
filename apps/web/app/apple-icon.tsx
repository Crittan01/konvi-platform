import { ImageResponse } from 'next/og'

// Icono para "Añadir a pantalla de inicio" en iOS (PNG generado en build).
export const size = { width: 180, height: 180 }
export const contentType = 'image/png'

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
          background: 'linear-gradient(180deg, #2E5C4A, #224438)',
        }}
      >
        <div
          style={{
            fontSize: 108,
            fontWeight: 800,
            color: '#FBFAF6',
            fontFamily: 'sans-serif',
            lineHeight: 1,
          }}
        >
          K
        </div>
        <div
          style={{
            position: 'absolute',
            right: 24,
            bottom: 24,
            width: 20,
            height: 20,
            borderRadius: 9999,
            background: '#D4A93A',
          }}
        />
      </div>
    ),
    { ...size },
  )
}
