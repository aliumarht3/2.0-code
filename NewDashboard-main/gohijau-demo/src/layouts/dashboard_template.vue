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
      </nav>
    </aside>
    
    <main class="flex-1 p-8">
      <slot></slot>
    </main>
  </div>
</template>