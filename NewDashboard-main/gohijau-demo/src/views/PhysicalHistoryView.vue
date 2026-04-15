<script setup>
import { ref, onMounted } from 'vue'
import apiClient from '../lib/apiClient'

const reports = ref([])
const machineId = "MAC001" // This should match the ID used in your Python script

onMounted(async () => {
  try {
    // This matches Endpoint G in your Program.cs
    const response = await apiClient.get(`/api/machine/physical-checks/${machineId}`)
    reports.value = response.data
  } catch (error) {
    console.error("Error fetching physical reports:", error)
  }
})
</script>

<template>
  <div class="p-6">
    <h1 class="text-2xl font-bold mb-4">Physical Check History</h1>
    <div v-for="report in reports" :key="report.id" class="mb-4 p-4 border rounded shadow">
      <p class="font-bold">Date: {{ new Date(report.timestamp).toLocaleString() }}</p>
      <ul>
        <li v-for="item in report.checks" :key="item.component">
          {{ item.component }}: {{ item.passed ? '✅ Pass' : '❌ Fail' }}
        </li>
      </ul>
    </div>
  </div>
</template>