<template>
  <DashboardLayout>
    <div class="mb-6 flex justify-between items-center">
      <div>
        <h1 class="text-3xl font-extrabold text-gray-900">Machine Diagnostics</h1>
        <p class="text-base text-gray-600 mt-1">Monitor startup sensors and perform manual hardware tests.</p>
      </div>
      
      <div class="flex gap-4 items-center">
        <div class="flex items-center gap-2">
          <label class="text-sm font-bold text-gray-700">Machine:</label>
          <select 
            v-model="selectedMachine" 
            class="bg-white border-2 border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-green-500 focus:border-green-500 block w-full p-2 font-medium shadow-sm"
          >
            <option value="GO-000001">GO-000001</option>
            <option value="GO-000002">GO-000002 (Live)</option>
            <option value="GO-000003">GO-000003</option>
          </select>
        </div>
      </div>
    </div>

    <Card class="bg-white text-gray-800 text-sm overflow-hidden p-0 shadow-lg border border-gray-200 rounded-xl mb-8">
      <div class="p-5 bg-gray-50 border-b border-gray-200 flex justify-between items-center">
        <span class="text-lg font-extrabold text-gray-800 tracking-wider uppercase flex items-center gap-2">
          🌐 Online Diagnostics (Startup Checks)
        </span>
        <button 
          @click="triggerOnlineDiagnostics" 
          :disabled="isOnlineRunning"
          :class="isOnlineRunning ? 'bg-gray-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'"
          class="text-sm text-white px-5 py-2.5 rounded-lg font-bold shadow-md transition-all flex items-center gap-2"
        >
          <span v-if="isOnlineRunning" class="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></span>
          {{ isOnlineRunning ? 'Running Tests...' : 'Re-run Startup Tests' }}
        </button>
      </div>
      
      <div class="overflow-x-auto">
        <table class="w-full text-left border-collapse table-fixed">
          <thead>
            <tr class="bg-gray-100 border-b-2 border-gray-200 text-gray-700 text-sm uppercase tracking-wider">
              <th class="p-4 font-extrabold w-16 text-center">No</th>
              <th class="p-4 font-extrabold w-56">Component</th>
              <th class="p-4 font-extrabold w-64">Checking Objective</th>
              <th class="p-4 font-extrabold w-32 text-center">Status</th>
              <th class="p-4 font-extrabold w-auto">How to Fix (Action)</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in onlineLogs" :key="log.no" class="border-b border-gray-200 hover:bg-gray-50 transition-colors">
              <td class="p-4 text-center text-gray-600 font-mono text-base font-bold">{{ log.no }}</td>
              <td class="p-4 font-bold text-gray-800 text-base">{{ log.component }}</td>
              <td class="p-4 text-gray-600 text-sm font-medium">{{ log.checking }}</td>
              <td class="p-4 text-center text-2xl flex justify-center items-center h-full">
                <span v-if="log.status === 'IN_PROGRESS'" class="flex justify-center mt-2">
                  <span class="animate-pulse block h-5 w-5 bg-yellow-400 rounded-full shadow-sm border-2 border-yellow-500"></span>
                </span>
                <svg v-else-if="log.status === '☑'" class="w-8 h-8 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                </svg>
                <svg v-else-if="log.status === 'X'" class="w-8 h-8 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
                <span v-else class="text-gray-400 text-sm font-bold uppercase tracking-wider mt-2 block">IDLE</span>
              </td>
              <td class="p-4 font-semibold text-sm text-red-600 leading-relaxed">
                {{ formatHumanAction(log.component, log.action) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <Card class="bg-white text-gray-800 text-sm overflow-hidden p-0 shadow-lg border border-gray-200 rounded-xl">
      <div class="p-5 bg-gray-50 border-b border-gray-200 flex justify-between items-center">
        <span class="text-lg font-extrabold text-gray-800 tracking-wider uppercase flex items-center gap-2">
          🛠️ Physical Diagnosis (Technician Mode)
        </span>
      </div>
      
      <div class="overflow-x-auto">
        <table class="w-full text-left border-collapse table-fixed">
          <thead>
            <tr class="bg-gray-100 border-b-2 border-gray-200 text-gray-700 text-sm uppercase tracking-wider">
              <th class="p-4 font-extrabold w-16 text-center">No</th>
              <th class="p-4 font-extrabold w-56">Component</th>
              <th class="p-4 font-extrabold w-64">Physical Action</th>
              <th class="p-4 font-extrabold w-32 text-center">Status</th>
              <th class="p-4 font-extrabold w-48 text-center">Manual Test</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in physicalLogs" :key="log.no" class="border-b border-gray-200 hover:bg-gray-50 transition-colors">
              <td class="p-4 text-center text-gray-600 font-mono text-base font-bold">{{ log.no }}</td>
              <td class="p-4 font-bold text-gray-800 text-base">{{ log.component }}</td>
              <td class="p-4 text-gray-600 text-sm font-medium">{{ log.checking }}</td>
              <td class="p-4 text-center flex justify-center items-center h-full">
                <svg v-if="log.status === '☑'" class="w-8 h-8 text-green-500 mt-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                </svg>
                <span v-else class="text-gray-400 text-sm font-bold uppercase tracking-wider mt-4 block">Waiting...</span>
              </td>
              <td class="p-4 text-center">
                <button 
                  @click="testPhysicalComponent(log.component)" 
                  class="bg-gray-800 hover:bg-black text-white text-xs px-4 py-2 rounded font-bold transition-all shadow-sm"
                >
                  RUN PART
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </DashboardLayout>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import * as signalR from '@microsoft/signalr';
import DashboardLayout from '@/layouts/dashboard_template.vue';
import Card from '@/components/Card.vue';

const selectedMachine = ref('GO-000002');
const isOnlineRunning = ref(false);
let connection = null;

// Human-friendly translations for technical actions (Requirement 5)
const humanizeMap = {
  'WiFi Connectivity': 'The machine lost internet. Please restart the Wi-Fi router or check the password.',
  'Weighing Tank (Ultrasonic)': 'The tank depth sensor is blocked. Please wipe the sensor inside the tank with a dry cloth.',
  'Weighing Tank (Load Cell)': 'The scale is showing the wrong weight. Ensure the tray is completely empty and nothing is pressing on it.',
  'Barrel': 'The main barrel level sensor is malfunctioning. Wipe the top sensor or ensure the barrel isn\'t overflowing.',
  'Filter #1': 'Water flow issue detected. The filter might be clogged with oil/debris. Please inspect and clean the filter.',
  'Door Sensors': 'The door appears to be open. Please ensure all machine doors are tightly closed and locked.'
};

const formatHumanAction = (component, rawAction) => {
  if (!rawAction) return "";
  // If the backend sent a raw technical string, we override it with our friendly language
  return humanizeMap[component] || rawAction;
};

// Default structures based on the PDF Requirements
const createDefaultLogs = () => {
  return {
    Online: [
      { no: 1, type: 'Online', component: 'WiFi Connectivity', checking: 'WiFi connection status', status: 'Idle', action: '' },
      { no: 2, type: 'Online', component: 'Weighing Tank (Ultrasonic)', checking: 'Object depth / Ultrasonic reading', status: 'Idle', action: '' },
      { no: 3, type: 'Online', component: 'Weighing Tank (Load Cell)', checking: 'Weight / Load cell reading', status: 'Idle', action: '' },
      { no: 4, type: 'Online', component: 'Barrel', checking: 'Storage level / Ultrasonic reading', status: 'Idle', action: '' },
      { no: 5, type: 'Online', component: 'Filter #1', checking: 'Flow & Turbidity status', status: 'Idle', action: '' },
      { no: 6, type: 'Online', component: 'Door Sensors', checking: 'Relay input / Security status', status: 'Idle', action: '' }
    ],
    Physical: [
      { no: 1, type: 'Physical', component: 'Pump', checking: 'Verify pump operates physically', status: 'Idle', action: '' },
      { no: 2, type: 'Physical', component: 'Qr Scanner', checking: 'Verify QR light is functioning', status: 'Idle', action: '' },
      { no: 3, type: 'Physical', component: 'Door Lock', checking: 'Verify door locking mechanism', status: 'Idle', action: '' },
      { no: 4, type: 'Physical', component: 'Wiper Motor', checking: 'Verify wiper sweeps properly', status: 'Idle', action: '' },
      { no: 5, type: 'Physical', component: 'Door Motor', checking: 'Verify door opens/closes smoothly', status: 'Idle', action: '' },
      { no: 6, type: 'Physical', component: 'Valve', checking: 'Verify valve actuates correctly', status: 'Idle', action: '' }
    ]
  };
};

const onlineLogs = ref(createDefaultLogs().Online);
const physicalLogs = ref(createDefaultLogs().Physical);

// Req 1: Trigger Startup diagnostics on Pi
const triggerOnlineDiagnostics = async () => {
  isOnlineRunning.value = true;
  
  // Set all to IN_PROGRESS so the user knows it started
  onlineLogs.value.forEach(log => {
    log.status = 'IN_PROGRESS';
    log.action = '';
  });

  try {
    await fetch(`http://localhost:5137/api/machine/${selectedMachine.value}/trigger-online`, {
      method: 'POST'
    });
  } catch (error) {
    console.error("Failed to trigger online diagnostic:", error);
    isOnlineRunning.value = false;
  }
};

// Req 2: Trigger Physical part test
const testPhysicalComponent = async (componentName) => {
  try {
    await fetch(`http://localhost:5137/api/machine/${selectedMachine.value}/trigger-physical/${encodeURIComponent(componentName)}`, {
      method: 'POST'
    });
    alert(`Test command sent to the machine for: ${componentName}`);
  } catch (error) {
    console.error("Failed to trigger physical diagnostic:", error);
  }
};

onMounted(async () => {
  connection = new signalR.HubConnectionBuilder()
    .withUrl("http://localhost:5137/machineHub")
    .withAutomaticReconnect()
    .build();

  connection.on("ReceiveDiagnosticLog", (log) => {
    if (log.machineId !== selectedMachine.value) return;

    if (log.status === '☑' || log.status === 'IN_PROGRESS') {
      log.action = "";
    }

    // Determine which array to update based on Type provided by C# backend
    const targetArray = log.type === 'Physical' ? physicalLogs.value : onlineLogs.value;
    const existingIndex = targetArray.findIndex(x => x.component === log.component);
    
    if (existingIndex !== -1) {
      targetArray[existingIndex].status = log.status;
      targetArray[existingIndex].action = log.action;
    }

    // If all online tests are no longer 'IN_PROGRESS', turn off the loading spinner
    if (!onlineLogs.value.some(l => l.status === 'IN_PROGRESS')) {
      isOnlineRunning.value = false;
    }
  });

  try {
    await connection.start();
    console.log("✅ Connected to Diagnostic Hub");
  } catch (err) {
    console.error("❌ SignalR Connection Error: ", err);
  }
});

watch(selectedMachine, () => {
  // Reset UI when switching machines
  onlineLogs.value = createDefaultLogs().Online;
  physicalLogs.value = createDefaultLogs().Physical;
});

onUnmounted(() => {
  if (connection) {
    connection.stop();
  }
});
</script>