using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.DependencyInjection;
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json; // ADD THIS
using System.IO;        // ADD THIS

var builder = WebApplication.CreateBuilder(args);

// 1. Allow your Vue dashboard to communicate with this server
builder.Services.AddCors(options =>
{
    options.AddPolicy("AllowVueDashboard", builder =>
    {
        builder.WithOrigins("http://localhost:5174") // MUST MATCH YOUR VUE PORT
               .AllowAnyHeader()
               .AllowAnyMethod()
               .AllowCredentials(); // CRITICAL for SignalR
    });
});

// 2. Add SignalR (WebSockets)
builder.Services.AddSignalR();

var app = builder.Build();
app.UseCors();

// 3. In-memory fake databases
var machines = new ConcurrentDictionary<string, MachineTelemetry>();
var diagnosticsStore = new ConcurrentDictionary<string, List<DiagnosticLog>>(); 

// --- NEW PERSISTENT STORAGE LOGIC ---
var physicalCheckReports = new List<PhysicalCheckReport>(); 
string dataFilePath = "physicalReports.json";

// Load existing data when the server starts
if (File.Exists(dataFilePath))
{
    var existingJson = File.ReadAllText(dataFilePath);
    physicalCheckReports = JsonSerializer.Deserialize<List<PhysicalCheckReport>>(existingJson) ?? new List<PhysicalCheckReport>();
}

app.UseCors("AllowVueDashboard");

// 4. SignalR Hub Mapping
app.MapHub<MachineHub>("/machineHub");

// ==========================================
// REST API ENDPOINTS
// ==========================================

// A. Receive Telemetry from Python script
app.MapPost("/api/machine/telemetry", async (IncomingPythonTelemetry payload, IHubContext<MachineHub> hubContext) =>
{
    var telemetry = new MachineTelemetry
    {
        MachineId = payload.MachineId,
        IsOnline = true,
        Metrics = payload.Metrics
    };

    machines[payload.MachineId] = telemetry;

    // --- NEW: Broadcast to frontend instantly ---
    await hubContext.Clients.All.SendAsync("ReceiveTelemetryUpdate", telemetry);

    return Results.Ok(new { message = "Telemetry saved and broadcasted." });
});

// B. Get Telemetry for the Dashboard
app.MapGet("/api/machine/telemetry", () =>
{
    return Results.Ok(machines.Values.ToList());
});

// C. Receive Live Diagnostic Updates from Raspberry Pi
app.MapPost("/api/machine/diagnostics", async (DiagnosticLog log, IHubContext<MachineHub> hubContext) =>
{
    // Make sure we have a list for this machine
    if (!diagnosticsStore.ContainsKey(log.MachineId))
    {
        diagnosticsStore[log.MachineId] = new List<DiagnosticLog>();
    }

    var machineLogs = diagnosticsStore[log.MachineId];

    // Update existing or add new
    var existing = machineLogs.FirstOrDefault(l => l.Component == log.Component);
    if (existing != null)
    {
        existing.Status = log.Status;
        existing.Action = log.Action;
        existing.Timestamp = log.Timestamp;
    }
    else
    {
        machineLogs.Add(log);
    }

    // Broadcast the update immediately to the Vue frontend via SignalR
    await hubContext.Clients.All.SendAsync("ReceiveDiagnosticLog", log);

    return Results.Ok(new { message = "Log received and broadcasted." });
});

// D. Trigger Online Diagnostics on the Raspberry Pi
app.MapPost("/api/machine/{machineId}/trigger-online", async (string machineId, IHubContext<MachineHub> hubContext) =>
{
    // Sends a command to Python to run startup checks
    await hubContext.Clients.All.SendAsync("RunOnlineDiagnostics", machineId);
    return Results.Ok(new { message = "Startup diagnostic command sent to machine." });
});

// E. Trigger a specific Physical Component test on the Raspberry Pi
app.MapPost("/api/machine/{machineId}/trigger-physical/{component}", async (string machineId, string component, IHubContext<MachineHub> hubContext) =>
{
    // Sends a command to Python to pulse a motor/relay
    await hubContext.Clients.All.SendAsync("RunPhysicalDiagnostics", machineId, component);
    return Results.Ok(new { message = $"Test command for {component} sent to machine." });
});

// F. Submit a new physical check report (From Technician UI)
app.MapPost("/api/machine/physical-checks", (PhysicalCheckReport report) =>
{
    report.Timestamp = DateTime.UtcNow; 
    physicalCheckReports.Add(report);

    // Save the updated list to the JSON file so it isn't lost on restart
    var jsonToSave = JsonSerializer.Serialize(physicalCheckReports);
    File.WriteAllText(dataFilePath, jsonToSave);

    return Results.Ok(new { message = "Physical check report saved successfully." });
});

// G. Get all past physical check reports for a specific machine
app.MapGet("/api/machine/physical-checks/{machineId}", (string machineId) =>
{
    var reports = physicalCheckReports
        .Where(r => r.MachineId == machineId)
        .OrderByDescending(r => r.Timestamp) // Newest first
        .ToList();
    return Results.Ok(reports);
});

// H. Send empty error logs so the Vue page doesn't crash (Placeholder)
app.MapGet("/api/machine/errors", () => Results.Ok(new List<object>()));

app.Run();

// ==========================================
// DATA MODELS & HUB
// ==========================================
public class MachineHub : Hub 
{ 
    public async Task SendStatus(string machineId, string status)
    {
        // This accepts the 5-second ping from Python and prevents the unhandled error
        await Clients.All.SendAsync("MachineStatusUpdate", machineId, status);
    }
}

public class IncomingPythonTelemetry {
    public string MachineId { get; set; }
    public MetricsData Metrics { get; set; }
}

public class MachineTelemetry {
    public string MachineId { get; set; }
    public bool IsOnline { get; set; }
    public MetricsData Metrics { get; set; }
}

public class MetricsData {
    public double WeightKg { get; set; }
    public double MainTankVolumeLiters { get; set; }
    public int TurbidityValue { get; set; }
    public double JunkTankDistanceCm { get; set; }
}

public class DiagnosticLog {
    public string MachineId { get; set; }
    public double Timestamp { get; set; }
    public int No { get; set; }
    public string Type { get; set; } // "Online" or "Physical"
    public string Component { get; set; }
    public string Checking { get; set; }
    public string Status { get; set; }
    public string Action { get; set; }
}

// Data models for the new physical check reporting system
public class PhysicalCheckItem {
    public string Component { get; set; }
    public bool Passed { get; set; }
}

public class PhysicalCheckReport {
    public string Id { get; set; } = Guid.NewGuid().ToString();
    public string MachineId { get; set; }
    public DateTime Timestamp { get; set; }
    public List<PhysicalCheckItem> Checks { get; set; } = new();
}