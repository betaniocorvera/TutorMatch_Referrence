/* ==========================================================
   TutorMatch A.I. — shared UI constants for Search
   No mock users or matching live here anymore. The server owns
   search, scoring, and public-profile data.
   ========================================================== */
(function (global) {
  'use strict';

  const DAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
  const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const DAY_IDS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

  // Coarse display windows. Search compares the exact slots stored in MySQL.
  const SLOTS = [
    { id: 'morning', label: 'Morning', start: '06:00', end: '12:00' },
    { id: 'afternoon', label: 'Afternoon', start: '12:00', end: '18:00' },
    { id: 'evening', label: 'Evening', start: '18:00', end: '24:00' }
  ];

  const LEVEL_LABELS = {
    elementary: 'Elementary',
    high_school: 'High school',
    senior_high: 'Senior high',
    college: 'College',
    adult: 'Adult learner'
  };

  const STYLE_LABELS = {
    visual: 'visual',
    step_by_step: 'step-by-step',
    discussion: 'discussion',
    practice: 'practice',
    real_world: 'real-world',
    structured: 'structured'
  };

  const GOAL_LABELS = {
    exam_prep: 'exam prep',
    conceptual: 'conceptual understanding',
    confidence: 'confidence',
    homework: 'homework',
    skill_building: 'skill building',
    grades: 'grades'
  };

  global.TutorMatchData = {
    DAYS,
    DAY_LABELS,
    DAY_IDS,
    SLOTS,
    LEVEL_LABELS,
    STYLE_LABELS,
    GOAL_LABELS
  };
})(window);
