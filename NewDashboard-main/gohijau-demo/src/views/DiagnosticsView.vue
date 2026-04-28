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
            <option value="GO-000001">GO-000001 (Perlis)</option>
            <option value="GO-000002">GO-000002</option>
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
                
                <svg v-else-if="log.status === 'X' || log.status === 'FAIL' || log.status === '❌'" class="w-8 h-8 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12"></path>
                </svg>

                <span v-else-if="log.status === 'Idle'" class="text-gray-400 text-sm font-bold uppercase tracking-wider mt-2 block">IDLE</span>
                
                <svg v-else class="w-8 h-8 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path>
                </svg>
              </td>
              <td class="p-4 font-semibold text-sm text-red-600 leading-relaxed">
                {{ formatHumanAction(log) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <Card class="bg-white text-gray-800 text-sm overflow-hidden p-0 shadow-lg border border-gray-200 rounded-xl mb-8">
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
              <th class="p-4 font-extrabold w-32 text-center">Passed?</th>
              <th class="p-4 font-extrabold w-48 text-center">Manual Test</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in physicalLogs" :key="log.no" class="border-b border-gray-200 hover:bg-gray-50 transition-colors">
              <td class="p-4 text-center text-gray-600 font-mono text-base font-bold">{{ log.no }}</td>
              <td class="p-4 font-bold text-gray-800 text-base">{{ log.component }}</td>
              <td class="p-4 text-gray-600 text-sm font-medium">{{ log.checking }}</td>
              <td class="p-4 text-center">
                <input 
                  type="checkbox" 
                  v-model="log.isChecked" 
                  class="w-6 h-6 text-green-600 bg-gray-100 border-gray-300 rounded focus:ring-green-500 cursor-pointer"
                >
              </td>
              <td class="p-4 text-center">
                <button 
                  v-if="log.component !== 'Qr Scanner'"
                  @click="testPhysicalComponent(log.component)" 
                  class="bg-gray-800 hover:bg-black text-white text-xs px-4 py-2 rounded font-bold transition-all shadow-sm"
                >
                  RUN PART
                </button>
                <span v-else class="text-xs font-bold text-gray-400 uppercase tracking-wider">
                  Auto (Check Visually)
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      
      <div class="p-4 bg-gray-50 border-t border-gray-200 flex justify-end">
        <button 
          @click="submitPhysicalChecks" 
          class="bg-green-600 hover:bg-green-700 text-white font-bold py-2 px-6 rounded-lg shadow-md transition-all flex items-center gap-2"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"></path></svg>
          Submit Physical Report
        </button>
      </div>
    </Card>
  </DashboardLayout>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import * as signalR from '@microsoft/signalr';
import DashboardLayout from '@/layouts/dashboard_template.vue';
import Card from '@/components/Card.vue';

const selectedMachine = ref('GO-000001');
const isOnlineRunning = ref(false);
let connection = null;

const humanizeMap = {
  'WiFi Connectivity': 'The machine lost internet. Please restart the Wi-Fi router or check the password.',
  'Weighing Tank (Ultrasonic)': 'The tank depth sensor is blocked. Please wipe the sensor inside the tank with a dry cloth.',
  'Weighing Tank (Load Cell)': 'The scale is showing the wrong weight. Ensure the tray is completely empty and nothing is pressing on it.',
  'Barrel': 'The main barrel level sensor is malfunctioning. Wipe the top sensor or ensure the barrel isn\'t overflowing.',
  'Filter #1': 'Water flow issue detected. The filter might be clogged with oil/debris. Please inspect and clean the filter.',
  'Door Sensors': 'The door appears to be open. Please ensure all machine doors are tightly closed and locked.'
};

// UPDATED: Now checks status first, and uses our custom map even if backend action is empty
const formatHumanAction = (log) => {
  // Only show action text if the test actually failed
  if (log.status !== 'FAIL' && log.status !== 'X') {
    return "";
  }
  // Return mapped text OR backend text OR default fallback
  return humanizeMap[log.component] || log.action || "Component failed check. Please inspect manually.";
};

const onlineLogs = ref([
  { no: 1, type: 'Online', component: 'WiFi Connectivity', checking: 'WiFi connection status', status: 'Idle', action: '' },
  { no: 2, type: 'Online', component: 'Weighing Tank (Ultrasonic)', checking: 'Object depth / Ultrasonic reading', status: 'Idle', action: '' },
  { no: 3, type: 'Online', component: 'Weighing Tank (Load Cell)', checking: 'Weight / Load cell reading', status: 'Idle', action: '' },
  { no: 4, type: 'Online', component: 'Barrel', checking: 'Storage level / Ultrasonic reading', status: 'Idle', action: '' },
  { no: 5, type: 'Online', component: 'Filter #1', checking: 'Flow & Turbidity status', status: 'Idle', action: '' },
  { no: 6, type: 'Online', component: 'Door Sensors', checking: 'Relay input / Security status', status: 'Idle', action: '' }
]);

const physicalLogs = ref([
  { no: 1, type: 'Physical', component: 'Pump', checking: 'Verify pump operates physically', isChecked: false },
  { no: 2, type: 'Physical', component: 'Qr Scanner', checking: 'Verify QR light is functioning (Always Flashing)', isChecked: false },
  { no: 3, type: 'Physical', component: 'Door Lock', checking: 'Verify door locking mechanism (Tech)', isChecked: false },
  { no: 4, type: 'Physical', component: 'Wiper Motor', checking: 'Verify wiper sweeps properly', isChecked: false },
  { no: 5, type: 'Physical', component: 'Door Motor', checking: 'Verify door opens/closes smoothly', isChecked: false },
  { no: 6, type: 'Physical', component: 'Valve', checking: 'Verify valve actuates correctly', isChecked: false }
]);

const triggerOnlineDiagnostics = async () => {
  isOnlineRunning.value = true;
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

const submitPhysicalChecks = async () => {
  const report = {
    machineId: selectedMachine.value,
    checks: physicalLogs.value.map(log => ({
      component: log.component,
      passed: log.isChecked
    }))
  };

  try {
    const response = await fetch(`http://localhost:5137/api/machine/physical-checks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(report)
    });

    if(response.ok) {
      alert('✅ Physical check report submitted successfully!');
      physicalLogs.value.forEach(log => log.isChecked = false);
    }
  } catch (error) {
    console.error("Failed to submit report:", error);
    alert('❌ Failed to submit the physical report.');
  }
};

onMounted(async () => {
  connection = new signalR.HubConnectionBuilder()
    .withUrl("http://localhost:5137/machineHub")
    .withAutomaticReconnect()
    .build();

  connection.on("ReceiveDiagnosticLog", (log) => {
    if (log.machineId !== selectedMachine.value) return;

    if (log.type === 'Online') {
      // UPDATED: Catch old Python name and map it to new Vue name automatically
      const targetComponent = log.component === 'Has WiFi?' ? 'WiFi Connectivity' : log.component;
      
      const existingIndex = onlineLogs.value.findIndex(x => x.component === targetComponent);
      if (existingIndex !== -1) {
        onlineLogs.value[existingIndex].status = log.status;
        onlineLogs.value[existingIndex].action = log.action;
      }
    }

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
  onlineLogs.value.forEach(log => {
    log.status = 'Idle';
    log.action = '';
  });
  physicalLogs.value.forEach(log => log.isChecked = false);
});

onUnmounted(() => {
  if (connection) {
    connection.stop();
  }
});
</script>