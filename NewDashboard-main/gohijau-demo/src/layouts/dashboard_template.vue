<script setup>
// Import the logo from your assets folder
import logoImg from '../assets/logo.png'
</script>

<template>
  <div class="min-h-screen flex flex-col md:flex-row">
    <aside class="w-full md:w-64 bg-green-800 text-white p-6 shadow-xl">
      
      <div class="flex items-center gap-3 mb-8">
        <img :src="logoImg" alt="Go-Hijau Logo" class="w-12 h-12 bg-white rounded-full p-1 shadow-sm" />
        <h2 class="text-xl font-bold">GoHijau Demo</h2>
      </div>

      <nav class="space-y-4">
        <router-link to="/" class="block hover:text-green-300">Telemetry</router-link>
        <router-link to="/diagnostics" active-class="text-green-300 font-bold" class="block hover:text-green-300">Diagnostics</router-link>
        <router-link to="/errors" class="block hover:text-green-300">Error Logs</router-link>
        <router-link 
          to="/physical-history" 
          class="flex items-center gap-3 px-4 py-3 rounded-xl transition-all font-semibold"
          :class="$route.path === '/physical-history' ? 'bg-green-600 text-white shadow-md' : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path>
          </svg>
          Physical History
        </router-link>
      </nav>
    </aside>
    
    <main class="flex-1 p-8">
      <slot></slot>
    </main>
  </div>
</template>