using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.DependencyInjection;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;

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
var diagnosticsStore = new ConcurrentDictionary<string, List<DiagnosticLog>>(); // NEW: Store live diagnostics history

app.UseCors("AllowVueDashboard");

// 4. SignalR Hub Mapping
app.MapHub<MachineHub>("/machineHub");

// ==========================================
// REST API ENDPOINTS
// ==========================================

// A. Receive Telemetry from Python script
app.MapPost("/api/machine/telemetry", (IncomingPythonTelemetry payload) =>
{
    // Format it for the Vue Dashboard
    machines[payload.MachineId] = new MachineTelemetry {
        MachineId = payload.MachineId,
        Location = "Local Testing Desk",
        IsOnline = true,
        Metrics = payload.Metrics
    };
    return Results.Ok(new { message = "Telemetry updated" });
});

// B. Send Telemetry to Vue Dashboard
app.MapGet("/api/machine/telemetry/latest", () =>
{
    return Results.Ok(machines.Values);
});

// C. Receive Table-based Diagnostics from Python & Broadcast instantly via SignalR to Vue
app.MapPost("/api/machine/diagnostics", async (DiagnosticLog payload, IHubContext<MachineHub> hubContext) =>
{
    // Maintain state in memory so switching dropdown updates instantly
    if (!diagnosticsStore.ContainsKey(payload.MachineId)) 
    {
        diagnosticsStore[payload.MachineId] = new List<DiagnosticLog>();
    }
    
    var list = diagnosticsStore[payload.MachineId];
    var existing = list.FirstOrDefault(x => x.No == payload.No);
    
    if (existing != null) {
        existing.Status = payload.Status;
        existing.Action = payload.Action;
        existing.Timestamp = payload.Timestamp;
    } else {
        list.Add(payload);
    }

    // Broadcast to Vue UI
    await hubContext.Clients.All.SendAsync("ReceiveDiagnosticLog", payload);
    return Results.Ok();
});

// NEW: Fetch specific machine's diagnostic table layout
app.MapGet("/api/machine/diagnostics/{machineId}", (string machineId) =>
{
    if (diagnosticsStore.TryGetValue(machineId, out var list)) {
        return Results.Ok(list.OrderBy(x => x.No));
    }
    return Results.Ok(new List<DiagnosticLog>());
});

// D. Send empty error logs so the Vue page doesn't crash
app.MapGet("/api/machine/errors", () => Results.Ok(new List<object>()));

app.Run();

// ==========================================
// DATA MODELS & HUB
// ==========================================
public class MachineHub : Hub { }

public class IncomingPythonTelemetry {
    public string MachineId { get; set; }
    public MetricsData Metrics { get; set; }
}

public class MachineTelemetry {
    public string MachineId { get; set; }
    public string Location { get; set; }
    public bool IsOnline { get; set; }
    public MetricsData Metrics { get; set; }
}

public class MetricsData {
    public double WeightKg { get; set; }
    public double MainTankVolumeLiters { get; set; }
    public int TurbidityValue { get; set; }
    public double JunkTankDistanceCm { get; set; }
}

// NEW: Diagnostic Table Row Model
public class DiagnosticLog {
    public string MachineId { get; set; }
    public double Timestamp { get; set; }
    public int No { get; set; }
    public string Component { get; set; }
    public string Checking { get; set; }
    public string Status { get; set; }
    public string Action { get; set; }
}