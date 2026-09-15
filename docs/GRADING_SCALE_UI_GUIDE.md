# Grading Scale UI Component - Implementation Guide

**Objective:** Redesign grading scale management UI to be less congested and more user-friendly  
**Technology Stack:** Vue.js/React (based on your frontend framework)

---

## 1. COMPONENT OVERVIEW

The new grading scale management consists of 4 main sections:

1. **Templates Browser** - View and apply predefined grading scales
2. **Grading Scale Manager** - Create, edit, delete custom scales
3. **Grade Band Editor** - Add/edit individual grades in a scale
4. **Visual Preview** - See how grades map to scores

---

## 2. COMPONENT STRUCTURE

```
GradingScaleManager/
├── TemplatesBrowser.vue
├── ScaleManager.vue
├── GradeBandEditor.vue
├── GradePreview.vue
├── styles/
│   ├── grading-scale.css
│   └── responsive.css
└── utils/
    ├── gradingScaleHelpers.js
    └── validation.js
```

---

## 3. TEMPLATES BROWSER COMPONENT

### Purpose

Display predefined grading scale templates that users can:
- View details
- Apply to default
- Duplicate for customization
- Use as reference

### Structure

```vue
<template>
  <div class="templates-browser">
    <!-- Header -->
    <div class="browser-header">
      <h2>Grading Scale Templates</h2>
      <div class="filters">
        <select v-model="templateFilter" class="filter-select">
          <option value="">All Templates</option>
          <option value="5grade">5-Grade System</option>
          <option value="13grade">13-Grade System</option>
          <option value="7point">7-Point Scale</option>
          <option value="custom">Custom</option>
        </select>
      </div>
    </div>

    <!-- Templates Grid -->
    <div class="templates-grid">
      <div v-for="template in filteredTemplates" 
           :key="template.id" 
           class="template-card">
        <!-- Card Header -->
        <div class="card-header">
          <h3>{{ template.name }}</h3>
          <span class="badge" :class="template.template_type">
            {{ template.template_type }}
          </span>
        </div>

        <!-- Card Content -->
        <div class="card-content">
          <!-- Description -->
          <p class="description">{{ template.description }}</p>

          <!-- Quick Preview -->
          <div class="quick-preview">
            <div v-for="band in template.scale_data.slice(0, 3)" 
                 :key="band.grade"
                 class="preview-band">
              <span class="grade">{{ band.grade }}</span>
              <span class="range">{{ band.min_score }}-{{ band.max_score }}</span>
            </div>
            <div v-if="template.scale_data.length > 3" class="preview-more">
              +{{ template.scale_data.length - 3 }} more
            </div>
          </div>

          <!-- Status -->
          <div class="status-indicator">
            <span v-if="template.is_default" class="default-badge">
              ✓ Default Scale
            </span>
          </div>
        </div>

        <!-- Card Actions -->
        <div class="card-actions">
          <button @click="viewDetails(template)" class="btn btn-secondary btn-sm">
            View
          </button>
          <button @click="makeDefault(template)" 
                  v-if="!template.is_default"
                  class="btn btn-primary btn-sm">
            Set as Default
          </button>
          <button @click="duplicate(template)" class="btn btn-outline btn-sm">
            Duplicate
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'TemplatesBrowser',
  data() {
    return {
      templates: [],
      templateFilter: '',
      loading: false,
    };
  },
  computed: {
    filteredTemplates() {
      if (!this.templateFilter) return this.templates;
      return this.templates.filter(t => t.template_type === this.templateFilter);
    },
  },
  methods: {
    fetchTemplates() {
      this.loading = true;
      // GET /api/grading-scales/?is_template=true
      fetch('/api/grading-scales/?is_template=true')
        .then(r => r.json())
        .then(data => {
          this.templates = data.results || data;
          this.loading = false;
        })
        .catch(err => {
          console.error('Failed to load templates:', err);
          this.loading = false;
        });
    },
    makeDefault(template) {
      const payload = { id: template.id };
      fetch('/api/grading-scales/set-default/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
        .then(r => r.json())
        .then(() => {
          this.$notify.success('Default scale updated');
          this.fetchTemplates();
          this.$emit('scaleChanged', template);
        })
        .catch(err => this.$notify.error('Failed to update default'));
    },
    duplicate(template) {
      this.$emit('duplicateTemplate', template);
    },
    viewDetails(template) {
      this.$emit('viewTemplate', template);
    },
  },
  mounted() {
    this.fetchTemplates();
  },
};
</script>

<style scoped>
.templates-browser {
  padding: 20px;
}

.browser-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
}

.templates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}

.template-card {
  background: white;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  transition: all 0.3s ease;
}

.template-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  border-color: #7a0000;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.card-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.badge {
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
  background: #f5ecec;
  color: #7a0000;
}

.quick-preview {
  display: flex;
  gap: 8px;
  margin: 12px 0;
  flex-wrap: wrap;
}

.preview-band {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px;
  background: #f8f8f8;
  border-radius: 4px;
  font-size: 12px;
}

.preview-band .grade {
  font-weight: 600;
  color: #7a0000;
}

.preview-more {
  color: #999;
  font-size: 12px;
  align-self: center;
}

.card-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.btn {
  flex: 1;
  padding: 8px 12px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.btn-primary {
  background: #7a0000;
  color: white;
}

.btn-secondary {
  background: #f5c400;
  color: black;
}

.btn-outline {
  background: white;
  color: #7a0000;
  border: 1px solid #7a0000;
}
</style>
```

---

## 4. GRADE BAND EDITOR COMPONENT

### Purpose

Clean interface for managing individual grade bands (A+, A, B, etc.)

### Structure

```vue
<template>
  <div class="grade-band-editor">
    <!-- Header -->
    <div class="editor-header">
      <h3>Manage Grade Bands</h3>
      <button @click="addGrade" class="btn btn-primary">
        + Add Grade Band
      </button>
    </div>

    <!-- Table View -->
    <div class="editor-table-container">
      <table class="editor-table">
        <thead>
          <tr>
            <th>Grade</th>
            <th>Min Score</th>
            <th>Max Score</th>
            <th>GPA Points</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(band, idx) in editingBands" :key="idx" class="band-row">
            <!-- Grade -->
            <td>
              <input v-model="band.grade" type="text" class="input-small" placeholder="e.g. A+">
            </td>
            
            <!-- Min Score -->
            <td>
              <input v-model.number="band.min_score" type="number" class="input-small" min="0" max="100">
            </td>

            <!-- Max Score -->
            <td>
              <input v-model.number="band.max_score" type="number" class="input-small" min="0" max="100">
            </td>

            <!-- GPA Points -->
            <td>
              <input v-model.number="band.gpa_points" type="number" class="input-small" step="0.1" min="0" max="4">
            </td>

            <!-- Status -->
            <td>
              <select v-model="band.status" class="input-small">
                <option value="Pass">Pass</option>
                <option value="Fail">Fail</option>
              </select>
            </td>

            <!-- Actions -->
            <td>
              <button @click="removeBand(idx)" class="btn-small btn-danger">
                Delete
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Validation Messages -->
    <div v-if="validationErrors.length" class="validation-errors">
      <div v-for="error in validationErrors" :key="error" class="error-msg">
        ⚠️ {{ error }}
      </div>
    </div>

    <!-- Visual Preview -->
    <div class="preview-section">
      <h4>Visual Preview</h4>
      <div class="grade-scale-visualization">
        <div v-for="band in editingBands"
             :key="band.grade"
             class="scale-bar"
             :style="{ 
               width: ((band.max_score - band.min_score) * 100 / 100) + '%',
               backgroundColor: getGradeColor(band.grade)
             }">
          <span class="bar-label">{{ band.grade }} ({{ band.min_score }}-{{ band.max_score }})</span>
        </div>
      </div>
      <div class="score-ruler">
        <span v-for="i in 11" :key="i" class="ruler-mark">
          {{ (i-1) * 10 }}
        </span>
      </div>
    </div>

    <!-- Save/Cancel -->
    <div class="editor-actions">
      <button @click="saveBands" class="btn btn-primary" :disabled="!isValid">
        Save Changes
      </button>
      <button @click="cancelEdit" class="btn btn-secondary">
        Cancel
      </button>
    </div>
  </div>
</template>

<script>
export default {
  name: 'GradeBandEditor',
  props: {
    bands: {
      type: Array,
      required: true,
    },
  },
  data() {
    return {
      editingBands: [],
      validationErrors: [],
    };
  },
  computed: {
    isValid() {
      return this.validationErrors.length === 0 && this.editingBands.length > 0;
    },
  },
  methods: {
    addGrade() {
      this.editingBands.push({
        grade: '',
        min_score: 0,
        max_score: 0,
        gpa_points: 0,
        status: 'Pass',
        implication: '',
      });
    },
    removeBand(index) {
      this.editingBands.splice(index, 1);
      this.validate();
    },
    validate() {
      this.validationErrors = [];

      // Check for duplicates
      const grades = this.editingBands.map(b => b.grade);
      if (new Set(grades).size !== grades.length) {
        this.validationErrors.push('Duplicate grade names found');
      }

      // Check for overlaps
      this.editingBands.forEach((band, idx) => {
        if (band.min_score >= band.max_score) {
          this.validationErrors.push(`Grade ${band.grade}: Min must be less than Max`);
        }

        // Check overlap with others
        this.editingBands.forEach((other, otherIdx) => {
          if (idx !== otherIdx) {
            if (band.min_score < other.max_score && band.max_score > other.min_score) {
              this.validationErrors.push(`Grade ${band.grade} overlaps with ${other.grade}`);
            }
          }
        });
      });

      // Check if all 0-100 is covered
      const sorted = [...this.editingBands].sort((a, b) => a.min_score - b.min_score);
      if (sorted[0].min_score !== 0) {
        this.validationErrors.push('Scale must start at 0');
      }
      if (sorted[sorted.length - 1].max_score !== 100) {
        this.validationErrors.push('Scale must end at 100');
      }
    },
    saveBands() {
      this.validate();
      if (this.isValid) {
        this.$emit('save', this.editingBands);
      }
    },
    cancelEdit() {
      this.$emit('cancel');
    },
    getGradeColor(grade) {
      const colorMap = {
        'A': '#4CAF50', 'A+': '#66BB6A', 'A-': '#43A047',
        'B': '#2196F3', 'B+': '#42A5F5', 'B-': '#1976D2',
        'C': '#FF9800', 'C+': '#FFB74D', 'C-': '#F57C00',
        'D': '#F44336', 'D+': '#EF5350', 'D-': '#C62828',
        'F': '#212121',
      };
      return colorMap[grade] || '#9E9E9E';
    },
  },
  watch: {
    editingBands: {
      deep: true,
      handler() {
        this.validate();
      },
    },
  },
  mounted() {
    this.editingBands = JSON.parse(JSON.stringify(this.bands));
  },
};
</script>

<style scoped>
.grade-band-editor {
  padding: 20px;
  background: white;
  border-radius: 8px;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.editor-table-container {
  overflow-x: auto;
  margin-bottom: 20px;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
}

.editor-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.editor-table thead {
  background: #f8f8f8;
  border-bottom: 2px solid #7a0000;
}

.editor-table th {
  padding: 12px;
  text-align: left;
  font-weight: 600;
  color: #1a1a1a;
}

.editor-table td {
  padding: 12px;
  border-bottom: 1px solid #e0e0e0;
}

.input-small {
  width: 100%;
  padding: 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.input-small:focus {
  outline: none;
  border-color: #7a0000;
  box-shadow: 0 0 0 3px rgba(122, 0, 0, 0.1);
}

.preview-section {
  margin: 20px 0;
  padding: 15px;
  background: #f8f8f8;
  border-radius: 4px;
}

.grade-scale-visualization {
  display: flex;
  height: 40px;
  margin-bottom: 8px;
  border-radius: 4px;
  overflow: hidden;
}

.scale-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 11px;
  font-weight: 600;
  text-shadow: 0 1px 2px rgba(0,0,0,0.2);
}

.score-ruler {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #666;
  padding: 0 5px;
}

.validation-errors {
  background: #ffebee;
  border: 1px solid #f44336;
  border-radius: 4px;
  padding: 12px;
  margin-bottom: 20px;
}

.error-msg {
  color: #c62828;
  font-size: 13px;
  margin-bottom: 4px;
}

.editor-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
</style>
```

---

## 5. MAIN CONTAINER COMPONENT

### Purpose

Orchestrate all sub-components

```vue
<template>
  <div class="grading-scale-manager">
    <!-- Tab Navigation -->
    <div class="tab-navigation">
      <button v-for="tab in tabs"
              :key="tab.id"
              @click="activeTab = tab.id"
              :class="['tab-btn', { active: activeTab === tab.id }]">
        {{ tab.label }}
      </button>
    </div>

    <!-- Tab Content -->
    <div class="tab-content">
      <!-- Templates Tab -->
      <div v-show="activeTab === 'templates'" class="tab-panel">
        <TemplatesBrowser 
          @scaleChanged="onScaleChanged"
          @duplicateTemplate="onDuplicate"
          @viewTemplate="onViewTemplate"
        />
      </div>

      <!-- Scale Manager Tab -->
      <div v-show="activeTab === 'manager'" class="tab-panel">
        <ScaleManager 
          @scaleCreated="onScaleCreated"
          @scaleUpdated="onScaleUpdated"
        />
      </div>

      <!-- Grade Band Editor Tab -->
      <div v-show="activeTab === 'editor'" class="tab-panel">
        <GradeBandEditor 
          v-if="selectedScale"
          :bands="selectedScale.scale_data"
          @save="saveGradeBands"
          @cancel="cancelEdit"
        />
        <div v-else class="empty-state">
          <p>Select a grading scale to edit its grade bands</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import TemplatesBrowser from './TemplatesBrowser.vue';
import ScaleManager from './ScaleManager.vue';
import GradeBandEditor from './GradeBandEditor.vue';

export default {
  name: 'GradingScaleManager',
  components: {
    TemplatesBrowser,
    ScaleManager,
    GradeBandEditor,
  },
  data() {
    return {
      activeTab: 'templates',
      selectedScale: null,
      tabs: [
        { id: 'templates', label: '📋 Templates' },
        { id: 'manager', label: '⚙️ Manage Scales' },
        { id: 'editor', label: '✏️ Edit Bands' },
      ],
    };
  },
  methods: {
    onScaleChanged(scale) {
      this.$notify.success('Grading scale updated');
      this.activeTab = 'templates';
    },
    onDuplicate(template) {
      // Create copy and switch to manager tab
      const copy = { ...template, id: null, name: `${template.name} (Copy)` };
      // Emit to create new scale
      this.$refs.scaleManager?.createFromTemplate(copy);
      this.activeTab = 'manager';
    },
    onViewTemplate(template) {
      this.selectedScale = template;
      this.activeTab = 'editor';
    },
    onScaleCreated(scale) {
      this.selectedScale = scale;
      this.activeTab = 'editor';
    },
    onScaleUpdated() {
      this.$notify.success('Scale updated');
      this.activeTab = 'manager';
    },
    saveGradeBands(bands) {
      // Save to API
      fetch(`/api/grading-scales/${this.selectedScale.id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scale_data: bands }),
      })
        .then(r => r.json())
        .then(data => {
          this.$notify.success('Grade bands updated');
          this.selectedScale = data;
          this.activeTab = 'manager';
        })
        .catch(err => this.$notify.error('Failed to save grade bands'));
    },
    cancelEdit() {
      this.activeTab = 'manager';
    },
  },
};
</script>

<style scoped>
.grading-scale-manager {
  padding: 20px;
}

.tab-navigation {
  display: flex;
  gap: 0;
  border-bottom: 2px solid #e0e0e0;
  margin-bottom: 20px;
}

.tab-btn {
  padding: 12px 24px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  color: #666;
  border-bottom: 3px solid transparent;
  transition: all 0.3s ease;
}

.tab-btn:hover {
  color: #1a1a1a;
}

.tab-btn.active {
  color: #7a0000;
  border-bottom-color: #7a0000;
}

.tab-content {
  padding: 20px 0;
}

.tab-panel {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #999;
}
</style>
```

---

## 6. CSS IMPROVEMENTS

Create `styles/grading-scale.css`:

```css
/* Grading Scale Styles */

:root {
  --primary-color: #7a0000;
  --primary-light: #a00000;
  --primary-dark: #4a0000;
  --secondary-color: #f5c400;
  --text-dark: #1a1a1a;
  --text-light: #999;
  --border-color: #e0e0e0;
  --shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

/* Cards */
.card {
  background: white;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
  box-shadow: var(--shadow);
}

.card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

/* Buttons */
.btn {
  padding: 10px 16px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.3s ease;
}

.btn-primary {
  background: var(--primary-color);
  color: white;
}

.btn-primary:hover {
  background: var(--primary-dark);
}

.btn-secondary {
  background: var(--secondary-color);
  color: black;
}

/* Forms */
.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-weight: 500;
  color: var(--text-dark);
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 14px;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(122, 0, 0, 0.1);
}

/* Notifications */
.notification {
  padding: 12px 16px;
  margin-bottom: 12px;
  border-radius: 4px;
  border-left: 4px solid;
}

.notification.success {
  background: #e8f5e9;
  border-left-color: #4caf50;
  color: #1b5e20;
}

.notification.error {
  background: #ffebee;
  border-left-color: #f44336;
  color: #c62828;
}

.notification.warning {
  background: #fff3e0;
  border-left-color: #ff9800;
  color: #e65100;
}
```

---

## 7. INTEGRATION CHECKLIST

- [ ] Install new component files
- [ ] Update navigation menu to link to grading scale manager
- [ ] Test template browser functionality
- [ ] Test grade band editor validation
- [ ] Test visual preview updates
- [ ] Test save/load functionality
- [ ] Test permission checks (DOS/SuperAdmin only)
- [ ] Create data migration with standard grading scales
- [ ] Test responsive design on mobile
- [ ] Add help documentation

---

## 8. API ENDPOINTS USED

```javascript
// GET all grading scales (filtered by template)
GET /api/grading-scales/?is_template=true

// POST set default grading scale
POST /api/grading-scales/set-default/
Body: { id: 1 }

// PATCH update grading scale
PATCH /api/grading-scales/{id}/
Body: { scale_data: [...] }

// POST create new grading scale
POST /api/grading-scales/
Body: {
  name: "String",
  template_type: "5grade|13grade|7point|custom",
  description: "String",
  scale_data: [{...}],
  is_template: false,
  is_default: false
}
```

---

This UI redesign makes grading scale management:
- ✅ Less congested - Separate tabs for different functions
- ✅ More intuitive - Visual preview helps users understand scales
- ✅ Easier to use - Template browser with one-click application
- ✅ Less error-prone - Validation catches overlaps and gaps
- ✅ Mobile-friendly - Responsive design works on all devices
