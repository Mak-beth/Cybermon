function initSeverityChart(low, medium, high, critical) {
  const ctx = document.getElementById("severityChart").getContext("2d");
  new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["Low", "Medium", "High", "Critical"],
      datasets: [{
        data: [low, medium, high, critical],
        backgroundColor: ["#28a745", "#ffc107", "#dc3545", "#7b0000"],
        borderColor: "#161b22",
        borderWidth: 3,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: "#8b949e", padding: 16, font: { size: 13 } },
        },
      },
      cutout: "60%",
    },
  });
}

function initHourlyTrendChart(hours, failed, unauthorized, offhours) {
  const ctx = document.getElementById("trendChart").getContext("2d");

  function radii(data) {
    return data.map(function(v) { return v > 0 ? 4 : 0; });
  }

  new Chart(ctx, {
    type: "line",
    data: {
      labels: hours,
      datasets: [
        {
          label: "Failed Logins",
          data: failed,
          borderColor: "#dc3545",
          tension: 0.3,
          fill: false,
          pointRadius: radii(failed),
          pointHoverRadius: 5,
        },
        {
          label: "Unauthorized Access",
          data: unauthorized,
          borderColor: "#ffc107",
          tension: 0.3,
          fill: false,
          pointRadius: radii(unauthorized),
          pointHoverRadius: 5,
        },
        {
          label: "Off-Hours Login",
          data: offhours,
          borderColor: "#3fb950",
          tension: 0.3,
          fill: false,
          pointRadius: radii(offhours),
          pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#8b949e" } },
      },
      scales: {
        x: {
          ticks: { color: "#6e7681" },
          grid:  { color: "#21262d" },
          title: {
            display: true,
            text: "Hour of Day (00–23)",
            color: "#aaa",
            font: { size: 12 },
          },
        },
        y: {
          beginAtZero: true,
          ticks: { color: "#6e7681", stepSize: 1, precision: 0 },
          grid:  { color: "#21262d" },
          title: {
            display: true,
            text: "Number of Violations",
            color: "#aaa",
            font: { size: 12 },
          },
        },
      },
    },
  });
}

function initWeeklyTrendChart(dates, failed, unauthorized, offhours) {
  const ctx = document.getElementById("weekChart").getContext("2d");

  function radii(data) {
    return data.map(function(v) { return v > 0 ? 4 : 0; });
  }

  new Chart(ctx, {
    type: "line",
    data: {
      labels: dates,
      datasets: [
        {
          label: "Failed Logins",
          data: failed,
          borderColor: "#dc3545",
          tension: 0.3,
          fill: false,
          pointRadius: radii(failed),
          pointHoverRadius: 5,
        },
        {
          label: "Unauthorized Access",
          data: unauthorized,
          borderColor: "#ffc107",
          tension: 0.3,
          fill: false,
          pointRadius: radii(unauthorized),
          pointHoverRadius: 5,
        },
        {
          label: "Off-Hours Login",
          data: offhours,
          borderColor: "#3fb950",
          tension: 0.3,
          fill: false,
          pointRadius: radii(offhours),
          pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#8b949e" } },
      },
      scales: {
        x: {
          ticks: { color: "#6e7681" },
          grid:  { color: "#21262d" },
          title: {
            display: true,
            text: "Date",
            color: "#aaa",
            font: { size: 12 },
          },
        },
        y: {
          beginAtZero: true,
          ticks: { color: "#6e7681", stepSize: 1, precision: 0 },
          grid:  { color: "#21262d" },
          title: {
            display: true,
            text: "Number of Violations",
            color: "#aaa",
            font: { size: 12 },
          },
        },
      },
    },
  });
}

function initTrendChart(labels, counts) {
  const ctx = document.getElementById("trendChart").getContext("2d");
  new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels,
      datasets: [{
        label: "Violations",
        data: counts,
        backgroundColor: "#dc3545cc",
        borderColor: "#dc3545",
        borderWidth: 1,
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#8b949e" } },
      },
      scales: {
        x: {
          ticks: { color: "#6e7681" },
          grid: { color: "#21262d" },
        },
        y: {
          beginAtZero: true,
          ticks: { color: "#6e7681", stepSize: 1 },
          grid: { color: "#21262d" },
        },
      },
    },
  });
}
