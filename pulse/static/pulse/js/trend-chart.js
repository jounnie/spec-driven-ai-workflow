// Trend chart (#14): draws #trend-chart from the JSON in #trend-data.
// Reads nothing else and makes no network requests. If Chart.js is missing or
// anything throws, the fallback message in the page stays visible.
(function () {
  'use strict';
  try {
    var dataElement = document.getElementById('trend-data');
    var canvas = document.getElementById('trend-chart');
    if (!window.Chart || !dataElement || !canvas) {
      return;
    }
    var data = JSON.parse(dataElement.textContent);
    var weeks = data.weeks;

    var series = [
      { key: 'workload', label: 'My workload is manageable', color: '#0072b2', shape: 'circle' },
      { key: 'clarity', label: 'Our goals and priorities are clear', color: '#c05000', shape: 'rect' },
      { key: 'collaboration', label: 'We work well together', color: '#00805c', shape: 'triangle' },
      { key: 'progress', label: 'I am confident we will deliver', color: '#1b1f24', shape: 'rectRot' }
    ];
    var background = '#ffffff';
    var muted = getComputedStyle(document.documentElement).getPropertyValue('--color-text-muted').trim() || '#525a66';

    var datasets = series.map(function (item) {
      return {
        label: item.label,
        data: weeks.map(function (week) { return week[item.key]; }),
        borderColor: item.color,
        borderWidth: 2,
        backgroundColor: item.color,
        pointStyle: item.shape,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBorderColor: item.color,
        pointBackgroundColor: weeks.map(function (week) { return week.limited ? background : item.color; }),
        pointHoverBackgroundColor: weeks.map(function (week) { return week.limited ? background : item.color; }),
        pointBorderWidth: 2,
        clip: false,
        spanGaps: false
      };
    });

    var whiteBackground = {
      id: 'whiteBackground',
      beforeDraw: function (chart) {
        var context = chart.ctx;
        context.save();
        context.globalCompositeOperation = 'destination-over';
        context.fillStyle = background;
        context.fillRect(0, 0, chart.width, chart.height);
        context.restore();
      }
    };

    function weekOf(items) {
      return weeks[items[0].dataIndex];
    }

    // Like Chart.js "index" mode, but also finds weeks whose value is null (gaps).
    window.Chart.Interaction.modes.weekIndex = function (chart, event) {
      var index = Math.round(chart.scales.x.getValueForPixel(event.x));
      if (event.x < chart.chartArea.left || event.x > chart.chartArea.right || index < 0 || index >= weeks.length) {
        return [];
      }
      var items = [];
      chart.data.datasets.forEach(function (dataset, datasetIndex) {
        var element = chart.getDatasetMeta(datasetIndex).data[index];
        if (element) {
          items.push({ element: element, datasetIndex: datasetIndex, index: index });
        }
      });
      return items;
    };

    new window.Chart(canvas, {
      type: 'line',
      data: { labels: weeks.map(function (week) { return week.week_key; }), datasets: datasets },
      plugins: [whiteBackground],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { top: 8, right: 8 } },
        animation: false,
        interaction: { mode: 'weekIndex', intersect: false },
        scales: {
          y: {
            min: data.scale_min,
            max: data.scale_max,
            ticks: { stepSize: 1, precision: 0, color: muted },
            grid: { color: '#e5e7eb' }
          },
          x: {
            ticks: { color: muted, autoSkip: true, maxRotation: 90, minRotation: 0 },
            grid: { color: '#e5e7eb' }
          }
        },
        plugins: {
          legend: { labels: { usePointStyle: true, color: muted } },
          tooltip: {
            callbacks: {
              title: function (items) { return weekOf(items).week_key; },
              beforeBody: function (items) {
                var week = weekOf(items);
                var lines = [week.range];
                if (week.count > 0) {
                  lines.push(week.count === 1 ? '1 response' : week.count + ' responses');
                }
                return lines;
              },
              label: function (item) {
                var week = weeks[item.dataIndex];
                if (week.count === 0) {
                  return item.datasetIndex === 0 ? 'No responses' : [];
                }
                return item.dataset.label + ': ' + week[series[item.datasetIndex].key].toFixed(1);
              },
              footer: function (items) {
                return weekOf(items).limited ? 'Limited anonymity' : '';
              }
            }
          }
        }
      }
    });
    var fallback = document.getElementById('chart-fallback');
    if (fallback) {
      fallback.hidden = true;
    }
  } catch (error) {
    // Leave the fallback message visible.
  }
}());
