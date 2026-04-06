using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.DependencyInjection;
using System.Collections.Concurrent;

var builder = WebApplication.CreateBuilder(args);

// 1. Allow your Vue dashboard to communicate with this server
builder.Services.AddCors(options => {
    options.AddDefaultPolicy(policy => {
        policy.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod();
    });
});

// 2. Add SignalR (WebSockets)
builder.Services.AddSignalR();

var app = builder.Build();
app.UseCors();

// 3. In-memory fake database
var machines = new ConcurrentDictionary<string, MachineTelemetry>();

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

// C. Receive Diagnostics from Python & Broadcast instantly via SignalR to Vue
app.MapPost("/api/machine/diagnostics", async (object payload, IHubContext<MachineHub> hubContext) =>
{
    // "ReceiveDiagnosticLog" must match what you put in your Vue.js code
    await hubContext.Clients.All.SendAsync("ReceiveDiagnosticLog", payload);
    return Results.Ok();
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