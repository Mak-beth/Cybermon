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
