<template>
  <DashboardLayout>
    <div class="mb-6 flex justify-between items-center">
      <div>
        <h1 class="text-3xl font-extrabold text-gray-900">Live Diagnostics</h1>
        <p class="text-base text-gray-600 mt-1">Monitor automated hardware tests during machine startup.</p>
      </div>
      
      <div class="flex gap-4 items-center">
        <div class="flex items-center gap-2">
          <label class="text-sm font-bold text-gray-700">Machine:</label>
          <select 
            v-model="selectedMachine" 
            class="bg-white border-2 border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2 font-medium shadow-sm"
          >
            <option value="GO-000001">GO-000001</option>
            <option value="GO-000002">GO-000002 (Live Demo)</option>
            <option value="GO-000003">GO-000003</option>
          </select>
        </div>

        <button @click="simulateLiveDiagnostics" class="text-sm bg-blue-600 hover:bg-blue-700 text-white px-5 py-2.5 rounded-lg font-bold shadow-md transition-all">
          Re-run Live Test (Demo)
        </button>
      </div>
    </div>

    <Card class="bg-white text-gray-800 text-sm overflow-hidden p-0 shadow-lg border border-gray-200 rounded-xl">
      <div class="p-5 bg-gray-50 border-b border-gray-200 flex justify-between items-center">
        <span class="text-lg font-extrabold text-gray-800 tracking-wider uppercase">Diagnostic Table: {{ selectedMachine }}</span>
        <span class="flex items-center gap-3">
          <span v-if="isRunning" class="relative flex h-4 w-4">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-4 w-4 bg-blue-600"></span>
          </span>
          <span :class="isRunning ? 'text-blue-600 font-bold text-base' : 'text-gray-500 font-medium text-base'">
            {{ isRunning ? 'Executing Test Sequence...' : 'Idle' }}
          </span>
        </span>
      </div>
      
      <div class="overflow-x-auto min-h-[400px]">
        <table class="w-full text-left border-collapse table-fixed">
          <thead>
            <tr class="bg-gray-100 border-b-2 border-gray-200 text-gray-700 text-sm uppercase tracking-wider">
              <th class="p-4 font-extrabold w-16 text-center">No</th>
              <th class="p-4 font-extrabold w-48">Component</th>
              <th class="p-4 font-extrabold w-64">Checking (Action / Part)</th>
              <th class="p-4 font-extrabold w-32 text-center">Status</th>
              <th class="p-4 font-extrabold w-auto">Required Action</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="currentMachineLogs.length === 0">
              <td colspan="5" class="p-10 text-center text-gray-500 text-base italic font-medium">
                No diagnostics data available for {{ selectedMachine }}.
              </td>
            </tr>
            <tr 
              v-for="(log, index) in currentMachineLogs" 
              :key="index" 
              class="border-b border-gray-200 hover:bg-gray-50 transition-colors"
            >
              <td class="p-4 text-center text-gray-600 font-mono text-base font-bold">{{ log.no }}</td>
              <td class="p-4 font-bold text-blue-700 text-base">{{ log.component }}</td>
              <td class="p-4 text-gray-700 text-sm font-medium">{{ log.checking }}</td>
              <td class="p-4 text-center text-2xl">
                <span v-if="log.status === 'IN_PROGRESS'" class="flex justify-center">
                  <span class="animate-pulse block h-5 w-5 bg-yellow-400 rounded-full shadow-sm"></span>
                </span>
                <span v-else-if="log.status === '☑'" class="text-green-600 font-extrabold">☑</span>
                <span v-else-if="log.status === 'X'" class="text-red-600 font-extrabold">X</span>
                <span v-else class="text-gray-600 text-base font-mono font-bold">{{ log.status }}</span>
              </td>
              <td class="p-4 font-bold text-base text-red-600 tracking-wide">
                {{ log.action }}
              </td>
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
const diagnosticState = ref({}); 
let connection = null;

const currentMachineLogs = computed(() => {
  let logs = diagnosticState.value[selectedMachine.value] || [];
  return logs.slice().sort((a, b) => a.no - b.no);
});

const fetchMachineDiagnostics = async (machineId) => {
  try {
    const res = await fetch(`http://localhost:5137/api/machine/diagnostics/${machineId}`);
    if (res.ok) {
      const data = await res.json();
      
      // Safety check: force action to be empty if status is ticked on initial load
      data.forEach(log => {
        if (log.status === '☑' || log.status === 'IN_PROGRESS') {
          log.action = "";
        }
      });
      
      diagnosticState.value[machineId] = data;
    }
  } catch (e) {
    console.error("Failed to fetch diagnostics for machine", e);
  }
};

watch(selectedMachine, (newVal) => {
  if (!diagnosticState.value[newVal]) {
    fetchMachineDiagnostics(newVal);
  }
});

onMounted(async () => {
  fetchMachineDiagnostics(selectedMachine.value);

  connection = new signalR.HubConnectionBuilder()
    .withUrl("http://localhost:5137/machineHub")
    .withAutomaticReconnect()
    .build();

  connection.on("ReceiveDiagnosticLog", (log) => {
    if (!diagnosticState.value[log.machineId]) {
      diagnosticState.value[log.machineId] = [];
    }
    
    // IMPORTANT NEW CODE: 
    // If the backend sent an action but the status is passed or testing, erase the action!
    if (log.status === '☑' || log.status === 'IN_PROGRESS') {
      log.action = "";
    }

    const logsArray = diagnosticState.value[log.machineId];
    const existingIndex = logsArray.findIndex(x => x.no === log.no);
    
    if (existingIndex !== -1) {
      logsArray[existingIndex] = log; 
    } else {
      logsArray.push(log); 
    }

    if (log.machineId === selectedMachine.value) {
      if (log.status === 'IN_PROGRESS') isRunning.value = true;
      if (log.status === '☑' || log.status === 'X') {
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
// DEMO SIMULATION
// ==========================================
const simulateLiveDiagnostics = () => {
  if (isRunning.value) return;
  
  diagnosticState.value[selectedMachine.value] = [];
  isRunning.value = true;
  
  const demoTests = [
    { no: 1, component: "WiFi Connectivity", checking: "Pinging local router for internet access", fail: false, failAction: "Reboot router or check credentials", delay: 1000 },
    { no: 2, component: "Weighing Tank", checking: "Load cell calibration and weight reading", fail: false, failAction: "Recalibrate load cell HX711", delay: 2500 },
    { no: 3, component: "Barrel", checking: "Ultrasonic sensor distance measurement", fail: true, failAction: "Clean sensor head / Inspect wiring", delay: 4000 },
    { no: 4, component: "Filter #1", checking: "Pump flow rate and pressure", fail: false, failAction: "Inspect pump for blockages", delay: 5500 },
    { no: 5, component: "Door Sensors", checking: "Magnetic relay contact closure", fail: false, failAction: "Ensure doors are fully closed", delay: 7000 }
  ];

  demoTests.forEach((test, index) => {
    setTimeout(() => {
      diagnosticState.value[selectedMachine.value].push({
        machineId: selectedMachine.value,
        no: test.no,
        component: test.component,
        checking: test.checking,
        status: "IN_PROGRESS",
        action: "" 
      });
    }, test.delay - 800);

    setTimeout(() => {
      const idx = diagnosticState.value[selectedMachine.value].findIndex(t => t.no === test.no);
      if (idx !== -1) {
        if (test.fail) {
          diagnosticState.value[selectedMachine.value][idx].status = "X";
          diagnosticState.value[selectedMachine.value][idx].action = `ACTION REQUIRED: ${test.failAction}`;
        } else {
          diagnosticState.value[selectedMachine.value][idx].status = "☑";
          diagnosticState.value[selectedMachine.value][idx].action = "";
        }
      }
      if (index === demoTests.length - 1) isRunning.value = false;
    }, test.delay);
  });
};
</script>