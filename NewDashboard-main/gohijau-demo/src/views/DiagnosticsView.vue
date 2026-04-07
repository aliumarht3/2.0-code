<template>
  <DashboardLayout>
    <div class="mb-6 flex justify-between items-center">
      <div>
        <h1 class="text-2xl font-bold text-gray-800">Live Diagnostics</h1>
        <p class="text-sm text-gray-500">Monitor automated hardware tests during machine startup.</p>
      </div>
      <button @click="simulateLiveDiagnostics" class="text-sm bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg font-medium">
        Re-run Live Test (Demo)
      </button>
    </div>

    <Card class="bg-gray-900 text-gray-100 font-mono text-sm overflow-hidden p-0">
      <div class="p-4 bg-gray-800 border-b border-gray-700 flex justify-between">
        <span>Terminal: Machine GO-000002</span>
        <span class="flex items-center gap-2">
          <span v-if="isRunning" class="relative flex h-3 w-3">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
          </span>
          <span :class="isRunning ? 'text-green-400' : 'text-gray-400'">
            {{ isRunning ? 'Receiving Data...' : 'Idle' }}
          </span>
        </span>
      </div>
      
      <div class="p-4 h-96 overflow-y-auto space-y-3" id="terminal-window">
        <div v-if="logs.length === 0" class="text-gray-500 italic">Waiting for machine startup sequence...</div>
        
        <div v-for="(log, index) in logs" :key="index" class="flex gap-4">
          <span class="text-gray-500 whitespace-nowrap">[{{ formatTime(log.timestamp) }}]</span>
          <span class="w-32 font-bold text-blue-400">[{{ log.step }}]</span>
          
          <span class="w-24" :class="getStatusColor(log.status)">{{ log.status }}</span>
          <span class="text-gray-300 flex-1">{{ log.detail }}</span>
        </div>
      </div>
    </Card>
  </DashboardLayout>
</template>

<script setup>
import { ref, nextTick, onMounted, onUnmounted } from 'vue';
import * as signalR from '@microsoft/signalr';
import DashboardLayout from '@/layouts/dashboard_template.vue';
import Card from '@/components/Card.vue';

const logs = ref([]);
const isRunning = ref(false);
let connection = null;

const formatTime = (timestamp) => {
  // Handles both Python floats (seconds) and JS integers (milliseconds)
  const date = new Date(timestamp > 9999999999 ? timestamp : timestamp * 1000);
  return date.toLocaleTimeString();
};

const getStatusColor = (status) => {
  switch(status) {
    case 'IN_PROGRESS': return 'text-yellow-400 animate-pulse';
    case 'PASSED': return 'text-green-400 font-bold';
    case 'FAILED': return 'text-red-500 font-bold';
    case 'ERROR': return 'text-red-500 font-bold';
    case 'COMPLETED': return 'text-blue-400 font-bold';
    default: return 'text-gray-400';
  }
};

// ==========================================
// LIVE SIGNALR CONNECTION
// ==========================================
onMounted(async () => {
  // Connect to your C# Hub URL
  connection = new signalR.HubConnectionBuilder()
    .withUrl("http://localhost:5137/machineHub")
    .withAutomaticReconnect()
    .build();

  // Listen for the broadcast from Program.cs
  connection.on("ReceiveDiagnostic", (log) => {
    isRunning.value = true;
    logs.value.push(log);
    scrollToBottom();
    
    if (log.status === 'COMPLETED' || log.status === 'ERROR') {
      isRunning.value = false;
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

const scrollToBottom = async () => {
  await nextTick();
  const terminal = document.getElementById('terminal-window');
  if (terminal) terminal.scrollTop = terminal.scrollHeight;
};

// ==========================================
// DEMO SIMULATION (For Testing)
// ==========================================
const simulateLiveDiagnostics = () => {
  if (isRunning.value) return;
  
  logs.value = [];
  isRunning.value = true;
  
  const demoSequence = [
    { step: "System Check", status: "IN_PROGRESS", detail: "Initializing startup sequence...", delay: 500 },
    { step: "Door Locks Test", status: "IN_PROGRESS", detail: "Testing solenoids (Unlock -> Lock)", delay: 1500 },
    { step: "Door Locks Test", status: "PASSED", detail: "Doors successfully locked and verified closed", delay: 3500 },
    { step: "System Check", status: "COMPLETED", detail: "Startup diagnostics finished. Machine ready.", delay: 4500 }
  ];

  demoSequence.forEach((item) => {
    setTimeout(() => {
      logs.value.push({
        timestamp: Date.now(),
        step: item.step,
        status: item.status,
        detail: item.detail
      });
      scrollToBottom();
      if(item.status === 'COMPLETED') isRunning.value = false;
    }, item.delay);
  });
};
</script>