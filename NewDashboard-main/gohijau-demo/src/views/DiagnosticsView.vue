<template>
  <DashboardLayout>
    <div class="mb-6 flex justify-between items-center">
      <div>
        <h1 class="text-2xl font-bold text-gray-800">Live Diagnostics</h1>
        <p class="text-sm text-gray-500">Monitor automated hardware tests during machine startup.</p>
      </div>
      
      <div class="flex gap-4 items-center">
        <div class="flex items-center gap-2">
          <label class="text-sm font-medium text-gray-500">Machine:</label>
          <select 
            v-model="selectedMachine" 
            class="bg-gray-800 border border-gray-700 text-white text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2"
          >
            <option value="GO-000001">GO-000001</option>
            <option value="GO-000002">GO-000002 (Live Demo)</option>
            <option value="GO-000003">GO-000003</option>
          </select>
        </div>

        <button @click="simulateLiveDiagnostics" class="text-sm bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium shadow-lg transition-all">
          Re-run Live Test (Demo)
        </button>
      </div>
    </div>

    <Card class="bg-gray-900 text-gray-100 text-sm overflow-hidden p-0 shadow-xl border border-gray-800">
      <div class="p-4 bg-gray-800 border-b border-gray-700 flex justify-between items-center">
        <span class="font-bold text-gray-300 tracking-wider">DIAGNOSTIC TABLE: {{ selectedMachine }}</span>
        <span class="flex items-center gap-2">
          <span v-if="isRunning" class="relative flex h-3 w-3">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
          </span>
          <span :class="isRunning ? 'text-green-400 font-bold' : 'text-gray-400'">
            {{ isRunning ? 'Executing Test Sequence...' : 'Idle' }}
          </span>
        </span>
      </div>
      
      <div class="overflow-x-auto min-h-[400px]">
        <table class="w-full text-left border-collapse">
          <thead>
            <tr class="bg-gray-800/50 border-b border-gray-700 text-gray-400 text-xs uppercase tracking-wide">
              <th class="p-4 font-semibold w-12 text-center">No</th>
              <th class="p-4 font-semibold">Component</th>
              <th class="p-4 font-semibold">Checking...</th>
              <th class="p-4 font-semibold w-24 text-center">Status</th>
              <th class="p-4 font-semibold w-32">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="currentMachineLogs.length === 0">
              <td colspan="5" class="p-8 text-center text-gray-500 italic">
                No diagnostics data available for {{ selectedMachine }}.
              </td>
            </tr>
            <tr 
              v-for="(log, index) in currentMachineLogs" 
              :key="index" 
              class="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
            >
              <td class="p-4 text-center text-gray-500 font-mono">{{ log.no }}</td>
              <td class="p-4 font-medium text-blue-300">{{ log.component }}</td>
              <td class="p-4 text-gray-400">{{ log.checking }}</td>
              <td class="p-4 text-center text-lg">
                <span v-if="log.status === 'IN_PROGRESS'" class="flex justify-center">
                  <span class="animate-pulse block h-3 w-3 bg-yellow-400 rounded-full"></span>
                </span>
                <span v-else-if="log.status === '☑'" class="text-green-500 font-bold">☑</span>
                <span v-else-if="log.status === 'X'" class="text-red-500 font-bold">X</span>
                <span v-else class="text-gray-500 text-sm font-mono">{{ log.status }}</span>
              </td>
              <td class="p-4 text-gray-400 text-xs">{{ log.action }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </DashboardLayout>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import * as signalR from '@microsoft/signalr';
import DashboardLayout from '@/layouts/dashboard_template.vue';
import Card from '@/components/Card.vue';

const selectedMachine = ref('GO-000002');
const isRunning = ref(false);
const diagnosticState = ref({}); // Stores logs mapped by machine ID
let connection = null;

// Returns current logs for selected machine, sorted by test number
const currentMachineLogs = computed(() => {
  let logs = diagnosticState.value[selectedMachine.value] || [];
  return logs.slice().sort((a, b) => a.no - b.no);
});

// Fetch historical table state from API
const fetchMachineDiagnostics = async (machineId) => {
  try {
    const res = await fetch(`http://localhost:5137/api/machine/diagnostics/${machineId}`);
    if (res.ok) {
      const data = await res.json();
      diagnosticState.value[machineId] = data;
    }
  } catch (e) {
    console.error("Failed to fetch diagnostics for machine", e);
  }
};

// Re-fetch when user changes machine in dropdown
watch(selectedMachine, (newVal) => {
  if (!diagnosticState.value[newVal]) {
    fetchMachineDiagnostics(newVal);
  }
});

// ==========================================
// LIVE SIGNALR CONNECTION
// ==========================================
onMounted(async () => {
  fetchMachineDiagnostics(selectedMachine.value);

  connection = new signalR.HubConnectionBuilder()
    .withUrl("http://localhost:5137/machineHub")
    .withAutomaticReconnect()
    .build();

  connection.on("ReceiveDiagnosticLog", (log) => {
    // If we haven't tracked this machine yet, initialize array
    if (!diagnosticState.value[log.machineId]) {
      diagnosticState.value[log.machineId] = [];
    }
    
    // Find if test "No" already exists in the table to update it, otherwise push
    const logsArray = diagnosticState.value[log.machineId];
    const existingIndex = logsArray.findIndex(x => x.no === log.no);
    
    if (existingIndex !== -1) {
      logsArray[existingIndex] = log; // Update row
    } else {
      logsArray.push(log); // Insert new row
    }

    // Toggle active spinning state based on progress
    if (log.machineId === selectedMachine.value) {
      if (log.status === 'IN_PROGRESS') isRunning.value = true;
      if (log.status === '☑' || log.status === 'X') {
        // If it's the last test (#11 in the PDF sequence), mark as idle
        if (log.no >= 11) isRunning.value = false;
      }
    }
  });

  try {
    await connection.start();
    console.log("✅ Connected to Diagnostic Hub");
  } catch (err) {
    console.error("❌ SignalR Connection Error: ", err);
  }
});

onUnmounted(() => {
  if (connection) {
    connection.stop();
  }
});

// ==========================================
// DEMO SIMULATION (For Testing Without Python)
// ==========================================
const simulateLiveDiagnostics = () => {
  if (isRunning.value) return;
  
  diagnosticState.value[selectedMachine.value] = [];
  isRunning.value = true;
  
  const demoTests = [
    { no: 1, component: "WiFi Connectivity", checking: "WiFi connection status", delay: 1000 },
    { no: 2, component: "Weighing Tank", checking: "Ultrasonic sensor, load cell, turbidity", delay: 2500 },
    { no: 3, component: "Barrel", checking: "Ultrasonic sensor reading", delay: 4000 },
    { no: 4, component: "Filter #1", checking: "Ultrasonic sensor reading", delay: 5500 },
    { no: 5, component: "Door Sensors", checking: "Arduino relay input reading", delay: 7000 }
  ];

  demoTests.forEach((test, index) => {
    // Stage 1: IN PROGRESS
    setTimeout(() => {
      diagnosticState.value[selectedMachine.value].push({
        machineId: selectedMachine.value,
        no: test.no,
        component: test.component,
        checking: test.checking,
        status: "IN_PROGRESS",
        action: "Testing..."
      });
    }, test.delay - 800);

    // Stage 2: PASSED
    setTimeout(() => {
      const idx = diagnosticState.value[selectedMachine.value].findIndex(t => t.no === test.no);
      if (idx !== -1) {
        diagnosticState.value[selectedMachine.value][idx].status = "☑";
        diagnosticState.value[selectedMachine.value][idx].action = "";
      }
      if (index === demoTests.length - 1) isRunning.value = false;
    }, test.delay);
  });
};
</script>