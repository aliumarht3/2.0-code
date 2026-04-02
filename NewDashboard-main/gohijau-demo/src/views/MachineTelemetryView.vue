<template>
  <DashboardLayout>
    <div class="mb-6 flex justify-between items-center">
      <h1 class="text-2xl font-bold text-gray-800">Machine Telemetry</h1>
      <button @click="fetchTelemetry" class="text-sm bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg flex items-center gap-2">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
        Refresh
      </button>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      <Card v-for="machine in machines" :key="machine.machineId" class="relative overflow-hidden">
        <div class="absolute top-4 right-4 flex items-center gap-2">
          <span class="relative flex h-3 w-3">
            <span :class="machine.isOnline ? 'bg-green-400' : 'bg-red-400'" class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"></span>
            <span :class="machine.isOnline ? 'bg-green-500' : 'bg-red-500'" class="relative inline-flex rounded-full h-3 w-3"></span>
          </span>
          <span class="text-xs font-semibold text-gray-600">{{ machine.isOnline ? 'Running' : 'Offline' }}</span>
        </div>

        <h2 class="text-lg font-bold text-gray-900 mb-1">{{ machine.machineId }}</h2>
        <p class="text-sm text-gray-500 mb-4 flex items-center gap-1">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.243-4.243a8 8 0 1111.314 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
          {{ machine.location || 'Location Not Set' }}
        </p>

        <div class="mb-4">
          <div class="flex justify-between text-sm mb-1">
            <span class="font-semibold text-gray-700">Main Tank (500L)</span>
            <span class="font-bold text-green-700">{{ machine.metrics?.mainTankVolumeLiters || 0 }} L</span>
          </div>
          <div class="w-full bg-gray-200 rounded-full h-3">
            <div 
              class="h-3 rounded-full transition-all duration-500"
              :class="getTankColor((machine.metrics?.mainTankVolumeLiters || 0) / 500 * 100)"
              :style="{ width: `${Math.min(((machine.metrics?.mainTankVolumeLiters || 0) / 500 * 100), 100)}%` }"
            ></div>
          </div>
          <p class="text-xs text-right mt-1 text-gray-500">{{ ((machine.metrics?.mainTankVolumeLiters || 0) / 500 * 100).toFixed(1) }}% Full</p>
        </div>

        <div class="grid grid-cols-2 gap-3 mt-4 pt-4 border-t border-gray-100">
          <div class="bg-gray-50 p-3 rounded-lg">
            <p class="text-xs text-gray-500 mb-1">Oil Quality (Turbidity)</p>
            <p class="text-sm font-bold" :class="machine.metrics?.turbidityValue > 600 ? 'text-red-600' : 'text-green-600'">
              {{ machine.metrics?.turbidityValue || 0 }} 
              <span class="text-xs font-normal text-gray-500">
                ({{ machine.metrics?.turbidityValue > 600 ? 'Poor' : 'Good' }})
              </span>
            </p>
          </div>
          <div class="bg-gray-50 p-3 rounded-lg">
            <p class="text-xs text-gray-500 mb-1">Junk Tank Lvl</p>
            <p class="text-sm font-bold text-gray-800">{{ machine.metrics?.junkTankDistanceCm || 0 }} cm <span class="text-xs font-normal text-gray-500">to top</span></p>
          </div>
        </div>
      </Card>
    </div>
  </DashboardLayout>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import DashboardLayout from '@/layouts/dashboard_template.vue';
import Card from '@/components/Card.vue';
import api from '@/lib/apiClient';

const machines = ref([]);

const getTankColor = (percentage) => {
  if (percentage >= 90) return 'bg-red-500';
  if (percentage >= 75) return 'bg-yellow-400';
  return 'bg-green-500';
};

const fetchTelemetry = async () => {
  try {
    // Note: Update this endpoint based on your actual .NET backend route
    const { data } = await api.get('/api/machine/telemetry/latest');
    machines.value = data;
  } catch (error) {
    console.error("Failed to fetch machine telemetry:", error);
    // Mock Data for testing the UI before backend is ready
    machines.value = [
      {
        machineId: "GO-000002",
        location: "GMI Student Center",
        isOnline: true,
        metrics: { mainTankVolumeLiters: 345.5, turbidityValue: 450, junkTankDistanceCm: 80 }
      },
      {
        machineId: "GO-000003",
        location: "Subang Jaya Parade",
        isOnline: false,
        metrics: { mainTankVolumeLiters: 490.0, turbidityValue: 800, junkTankDistanceCm: 15 }
      }
    ];
  }
};

onMounted(() => {
  fetchTelemetry();
});
</script>