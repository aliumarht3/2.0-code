<template>
  <DashboardLayout>
    <div class="mb-6">
      <h1 class="text-2xl font-bold text-gray-800">Hardware Error Logs</h1>
      <p class="text-sm text-gray-500">Monitor automated hardware fault reports to diagnose machine malfunctions.</p>
    </div>

    <Card class="overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm text-left text-gray-500">
          <thead class="text-xs text-gray-700 uppercase bg-gray-50 border-b">
            <tr>
              <th scope="col" class="px-6 py-3">Timestamp</th>
              <th scope="col" class="px-6 py-3">Machine ID</th>
              <th scope="col" class="px-6 py-3">Component</th>
              <th scope="col" class="px-6 py-3">Error Description</th>
              <th scope="col" class="px-6 py-3">Severity</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in logs" :key="log.id" class="bg-white border-b hover:bg-gray-50">
              <td class="px-6 py-4 whitespace-nowrap">{{ new Date(log.timestamp).toLocaleString() }}</td>
              <td class="px-6 py-4 font-bold text-gray-900">{{ log.machineId }}</td>
              <td class="px-6 py-4">{{ log.component }}</td>
              <td class="px-6 py-4">{{ log.description }}</td>
              <td class="px-6 py-4">
                <span :class="getSeverityClass(log.severity)" class="px-2.5 py-0.5 rounded-full text-xs font-medium">
                  {{ log.severity }}
                </span>
              </td>
            </tr>
            <tr v-if="logs.length === 0">
              <td colspan="5" class="px-6 py-8 text-center text-gray-500">No hardware errors detected. System is healthy.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </DashboardLayout>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import DashboardLayout from '@/layouts/dashboard_template.vue';
import Card from '@/components/Card.vue';
import api from '@/lib/apiClient';

const logs = ref([]);

const getSeverityClass = (severity) => {
  switch (severity?.toUpperCase()) {
    case 'CRITICAL': return 'bg-red-100 text-red-800 border-red-200 border';
    case 'WARNING': return 'bg-yellow-100 text-yellow-800 border-yellow-200 border';
    default: return 'bg-blue-100 text-blue-800 border-blue-200 border';
  }
};

const fetchLogs = async () => {
  try {
    const { data } = await api.get('/api/machine/errors');
    logs.value = data;
  } catch (error) {
    console.error("Failed to fetch logs:", error);
    // Mock Data
    logs.value = [
      { id: 1, timestamp: new Date().toISOString(), machineId: "GO-000002", component: "PUMP_SYSTEM", description: "Pump timeout reached (120s). Possible blockage or dry run.", severity: "CRITICAL" },
      { id: 2, timestamp: new Date(Date.now() - 3600000).toISOString(), machineId: "GO-000002", component: "SENSOR_UNO", description: "Scale failed to tare after 3 attempts.", severity: "WARNING" }
    ];
  }
};

onMounted(() => fetchLogs());
</script>