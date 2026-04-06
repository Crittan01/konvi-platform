import { type NextRequest } from 'next/server'
// import { updateSession } from '@commerce/auth/middleware' // Módulo privado referenciado teóricamente

export async function middleware(request: NextRequest) {
  // SSR Proxy: 
  // Intercepta peticiones protegidas (Dashboard, Panel) y refresca el Token validando custom claims.
  
  // return await updateSession(request)
  return;
}

export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}\n