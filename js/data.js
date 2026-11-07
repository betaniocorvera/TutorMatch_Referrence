/* ==========================================================
   TutorMatch A.I. — mock data + placeholder matching
   UI-only. No backend calls. Replace this module with the
   real API / KNN later.
   ========================================================== */
(function (global) {
  'use strict';

  const DAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
  const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const SLOTS = ['Morning', 'Afternoon', 'Evening'];

  // 7 characters per row = Mon..Sun. 1 = available.
  const grid = (morning, afternoon, evening) =>
    [morning, afternoon, evening].map((row) => row.split('').map((c) => c === '1'));

  const tutors = [
    {
      id: 'tutor_maria',
      email: 'maria@example.test',
      name: 'Maria Santos',
      role: 'tutor',
      subjects: ['Mathematics', 'Algebra', 'Calculus'],
      styles: ['structured', 'visual'],
      format: 'online',
      rate: 18,
      distanceKm: 2.4,
      area: 'Brgy. 4, Cabadbaran City',
      bio: 'Patient math tutor with 6 years of experience helping senior high and college students build confidence step by step.',
      availability: grid('1010100', '0101011', '1111100')
    },
    {
      id: 'tutor_james',
      name: 'James Reyes',
      role: 'tutor',
      subjects: ['Physics', 'Chemistry'],
      styles: ['hands-on', 'discussion'],
      format: 'either',
      rate: 22,
      distanceKm: 3.1,
      area: 'Brgy. 7, Cabadbaran City',
      bio: 'Science tutor who uses experiments, diagrams, and real-world examples to make abstract topics click.',
      availability: grid('0101000', '1010110', '1101101')
    },
    {
      id: 'tutor_aisha',
      name: 'Aisha Rahman',
      role: 'tutor',
      subjects: ['English', 'IELTS'],
      styles: ['discussion', 'visual'],
      format: 'online',
      rate: 20,
      distanceKm: 5.8,
      area: 'Brgy. 2, Cabadbaran City',
      bio: 'IELTS coach and English tutor focused on speaking confidence, essay structure, and practical exam strategies.',
      availability: grid('1111100', '0000011', '1010100')
    },
    {
      id: 'tutor_daniel',
      name: 'Daniel Cruz',
      role: 'tutor',
      subjects: ['Python', 'Mathematics'],
      styles: ['hands-on', 'structured'],
      format: 'online',
      rate: 25,
      distanceKm: 1.7,
      area: 'Brgy. 9, Cabadbaran City',
      bio: 'Software developer who teaches Python through small projects, debugging practice, and clear weekly milestones.',
      availability: grid('0000011', '1111100', '1101110')
    },
    {
      id: 'tutor_grace',
      name: 'Grace Lim',
      role: 'tutor',
      subjects: ['Biology', 'Chemistry'],
      styles: ['visual', 'discussion'],
      format: 'in-person',
      rate: 16,
      distanceKm: 8.2,
      area: 'Brgy. 11, Cabadbaran City',
      bio: 'Biology and chemistry tutor who prefers face-to-face sessions with printed diagrams and guided practice.',
      availability: grid('1010110', '0101001', '1110100')
    },
    {
      id: 'tutor_paolo',
      name: 'Paolo Mendoza',
      role: 'tutor',
      subjects: ['Algebra', 'Physics'],
      styles: ['structured', 'hands-on'],
      format: 'either',
      rate: 14,
      distanceKm: 12.5,
      area: 'Brgy. 5, Cabadbaran City',
      bio: 'Affordable algebra and physics tutor for junior high students who need steady weekly review.',
      availability: grid('1101011', '1010100', '0101010')
    }
  ];

  const students = [
    {
      id: 'student_ana',
      email: 'ana@example.test',
      name: 'Ana Villanueva',
      role: 'student',
      subjects: ['Mathematics', 'Algebra'],
      styles: ['visual', 'structured'],
      format: 'online',
      budget: 25,
      distanceKm: 2.0,
      area: 'Brgy. 3, Cabadbaran City',
      bio: 'Grade 11 student preparing for college entrance tests. Looking for weekly algebra review and problem-solving practice.',
      availability: grid('1010100', '0101011', '1111100')
    },
    {
      id: 'student_ben',
      name: 'Ben Torres',
      role: 'student',
      subjects: ['Physics', 'Calculus'],
      styles: ['hands-on', 'discussion'],
      format: 'either',
      budget: 30,
      distanceKm: 4.5,
      area: 'Brgy. 8, Cabadbaran City',
      bio: 'Engineering freshman who wants help connecting calculus concepts to physics problems.',
      availability: grid('0101000', '1010110', '1101101')
    },
    {
      id: 'student_chloe',
      name: 'Chloe Garcia',
      role: 'student',
      subjects: ['English', 'IELTS'],
      styles: ['discussion', 'visual'],
      format: 'online',
      budget: 18,
      distanceKm: 6.3,
      area: 'Brgy. 1, Cabadbaran City',
      bio: 'Working student aiming for an IELTS band 7. Needs speaking practice and writing feedback.',
      availability: grid('1111100', '0000011', '1010100')
    },
    {
      id: 'student_ethan',
      name: 'Ethan Ramos',
      role: 'student',
      subjects: ['Python', 'Mathematics'],
      styles: ['hands-on', 'structured'],
      format: 'online',
      budget: 28,
      distanceKm: 3.8,
      area: 'Brgy. 10, Cabadbaran City',
      bio: 'IT student learning Python for data analysis. Prefers project-based sessions with clear exercises.',
      availability: grid('0000011', '1111100', '1101110')
    },
    {
      id: 'student_hana',
      name: 'Hana Suzuki',
      role: 'student',
      subjects: ['Chemistry', 'Biology'],
      styles: ['visual', 'discussion'],
      format: 'in-person',
      budget: 20,
      distanceKm: 9.1,
      area: 'Brgy. 12, Cabadbaran City',
      bio: 'Nursing applicant reviewing chemistry and biology. Learns best with diagrams and face-to-face discussion.',
      availability: grid('1010110', '0101001', '1110100')
    },
    {
      id: 'student_miguel',
      name: 'Miguel Flores',
      role: 'student',
      subjects: ['Algebra', 'Physics'],
      styles: ['structured', 'hands-on'],
      format: 'either',
      budget: 15,
      distanceKm: 11.0,
      area: 'Brgy. 6, Cabadbaran City',
      bio: 'Junior high student who needs patient weekly help with algebra fundamentals and physics homework.',
      availability: grid('1101011', '1010100', '0101010')
    }
  ];

  const users = tutors.concat(students);

  function normalizeRole(role) {
    return role === 'tutor' ? 'tutor' : 'student';
  }

  function getMe(session) {
    const safe = session || {};
    const email = String(safe.email || '').toLowerCase();
    const found = users.find((u) => u.email && u.email.toLowerCase() === email);
    const role = normalizeRole(safe.role || (found && found.role));

    if (found) {
      return { ...found, name: safe.name || found.name, role, maxDistanceKm: 5 };
    }

    const isStudent = role === 'student';
    return {
      id: 'me',
      role,
      name: safe.name || (isStudent ? 'Student Name' : 'Tutor Name'),
      email: safe.email || '',
      subjects: isStudent
        ? ['Mathematics', 'Algebra', 'Calculus', 'Physics']
        : ['Mathematics', 'Algebra', 'Physics'],
      styles: isStudent ? ['visual', 'structured'] : ['structured', 'visual'],
      format: 'either',
      budget: 25,
      rate: 18,
      maxDistanceKm: 5,
      area: 'Cabadbaran City',
      bio: '',
      availability: grid('1010100', '0101011', '1111100')
    };
  }

  function formatCompatible(a, b) {
    if (!a || !b) return true;
    return a === 'either' || b === 'either' || a === b;
  }

  function hasAvailability(user, key) {
    const rows = (user && user.availability) || [];
    if (key === 'weekday-am') return Boolean(rows[0] && rows[0].slice(0, 5).some(Boolean));
    if (key === 'weekday-pm') return Boolean(rows[1] && rows[1].slice(0, 5).some(Boolean));
    if (key === 'weekday-eve') return Boolean(rows[2] && rows[2].slice(0, 5).some(Boolean));
    if (key === 'weekend') {
      return [0, 1, 2].some((s) => rows[s] && (rows[s][5] || rows[s][6]));
    }
    return true;
  }

  function availabilityOverlap(me, other) {
    const a = (me && me.availability) || [];
    const b = (other && other.availability) || [];
    const labels = [];
    for (let slot = 0; slot < 3; slot += 1) {
      for (let day = 0; day < 7; day += 1) {
        if (a[slot] && a[slot][day] && b[slot] && b[slot][day]) {
          labels.push({ slot, day, label: DAY_LABELS[day] + ' ' + SLOTS[slot] });
        }
      }
    }
    return { count: labels.length, labels };
  }

  function intersection(a, b) {
    const left = a || [];
    const right = b || [];
    return left.filter((item) => right.indexOf(item) !== -1);
  }

  function budgetFits(me, other) {
    if (me.role === 'student') {
      return other.role === 'tutor' && typeof other.rate === 'number' && other.rate <= me.budget;
    }
    return other.role === 'student' && typeof other.budget === 'number' && other.budget >= me.rate;
  }

  function matchesText(other, query) {
    if (!query) return true;
    const haystack = [
      other.name,
      other.role,
      other.area,
      other.bio,
      ...(other.subjects || [])
    ].join(' ').toLowerCase();
    return haystack.indexOf(query.toLowerCase()) !== -1;
  }

  function hardFilter(me, other, filters, query) {
    const f = filters || {};
    if (!other || other.role === me.role) return false;
    if (!formatCompatible(me.format, other.format)) return false;
    if (!budgetFits(me, other)) return false;
    if (!matchesText(other, query || '')) return false;

    const subject = String(f.subject || 'all').toLowerCase();
    if (subject !== 'all' && !(other.subjects || []).some((s) => s.toLowerCase() === subject)) {
      return false;
    }

    if (f.format && f.format !== 'any' && f.format !== 'either') {
      if (!formatCompatible(f.format, other.format)) return false;
    }

    const price = other.role === 'tutor' ? other.rate : other.budget;
    if (f.price === 'under-15' && !(price < 15)) return false;
    if (f.price === '15-25' && !(price >= 15 && price <= 25)) return false;
    if (f.price === '25-35' && !(price > 25 && price <= 35)) return false;
    if (f.price === '35-plus' && !(price > 35)) return false;

    if (f.availability && f.availability !== 'any' && !hasAvailability(other, f.availability)) {
      return false;
    }

    if (f.distance && f.distance !== 'any') {
      const max = Number(f.distance);
      if (Number.isFinite(max) && other.distanceKm > max) return false;
    }

    return true;
  }

  // Placeholder. The real K-Nearest Neighbors replaces this.
  function mockScore(me, other) {
    const subjectMatches = intersection(me.subjects, other.subjects);
    const subjectScore = Math.min(1, subjectMatches.length / Math.max(1, (me.subjects || []).length));

    const overlap = availabilityOverlap(me, other);
    const mySlots = ((me.availability || []).flat().filter(Boolean).length) || 1;
    const availabilityScore = Math.min(1, overlap.count / mySlots);

    const styleMatches = intersection(me.styles, other.styles);
    const styleScore = Math.min(1, styleMatches.length / Math.max(1, (me.styles || []).length));

    const formatScore = formatCompatible(me.format, other.format) ? 1 : 0;
    const budgetScore = budgetFits(me, other) ? 1 : 0;

    const radius = me.maxDistanceKm || me.distanceKm || 10;
    const distanceScore = Math.max(0, 1 - Math.min(1, other.distanceKm / radius));

    const score = Math.round(
      subjectScore * 30 +
      availabilityScore * 25 +
      styleScore * 15 +
      formatScore * 10 +
      budgetScore * 10 +
      distanceScore * 10
    );

    const reasons = [];

    const subjectList = (subjectMatches.length ? subjectMatches : (other.subjects || [])).slice(0, 2);
    if (subjectList.length) {
      reasons.push(
        me.role === 'student'
          ? 'Teaches ' + subjectList.join(' & ')
          : 'Learning ' + subjectList.join(' & ')
      );
    }

    if (overlap.count > 0) {
      const weekdayEvening = overlap.labels.some(
        (item) => item.slot === 2 && item.day <= 4
      );
      const weekdayMorning = overlap.labels.some(
        (item) => item.slot === 0 && item.day <= 4
      );
      const weekdayAfternoon = overlap.labels.some(
        (item) => item.slot === 1 && item.day <= 4
      );
      if (weekdayEvening) reasons.push('Free on your weekday evenings');
      else if (weekdayMorning) reasons.push('Free on your weekday mornings');
      else if (weekdayAfternoon) reasons.push('Free on your weekday afternoons');
      else reasons.push('Has some overlapping availability');
    } else {
      reasons.push('Has availability you can request');
    }

    reasons.push(
      me.role === 'student'
        ? 'Rate fits your budget'
        : 'Budget covers your rate'
    );

    if (reasons.length < 3) {
      if (formatCompatible(me.format, other.format)) {
        reasons.push(other.format === 'either' ? 'Offers online or in-person' : 'Format matches your preference');
      }
      if (other.distanceKm <= radius) reasons.push('Only ' + other.distanceKm.toFixed(1) + ' km away');
      if (styleMatches.length) reasons.push('Prefers ' + styleMatches.join(' & ') + ' learning');
    }

    return { score: Math.max(0, Math.min(100, score)), reasons: reasons.slice(0, 3) };
  }

  function searchUsers(me, query, filters) {
    return users
      .filter((other) => hardFilter(me, other, filters, query))
      .map((other) => {
        const result = mockScore(me, other);
        return { ...other, score: result.score, reasons: result.reasons };
      })
      .sort((a, b) => b.score - a.score || a.distanceKm - b.distanceKm);
  }

  const api = {
    DAYS,
    DAY_LABELS,
    SLOTS,
    users,
    tutors,
    students,
    normalizeRole,
    getMe,
    hardFilter,
    mockScore,
    searchUsers,
    availabilityOverlap
  };

  global.TutorMatchData = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

})(typeof window !== 'undefined' ? window : globalThis);
