import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  preview: {
    // Railway provides a public hostname; allow it in preview server.
    // Using `true` keeps deployments simple.
    allowedHosts: true,
  },
})
